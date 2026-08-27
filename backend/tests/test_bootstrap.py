"""The first-run administrator.

One rule carries all the safety: it only ever runs when the users table is empty.
"""

import pytest

from app.bootstrap import ensure_bootstrap_admin
from app.config import settings


class FakeSession:
    """Enough of AsyncSession for the guard logic, with no database."""

    def __init__(self, user_count: int):
        self._count = user_count
        self.added: list = []
        self.committed = False
        self.rolled_back = False

    async def scalar(self, _stmt):
        return self._count

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


@pytest.fixture(autouse=True)
def clean_settings(monkeypatch):
    monkeypatch.setattr(settings, "bootstrap_admin_email", "")
    monkeypatch.setattr(settings, "bootstrap_admin_password", "")
    monkeypatch.setattr(settings, "bootstrap_admin_name", "Platform Admin")


async def test_nothing_happens_without_an_email():
    session = FakeSession(user_count=0)
    assert await ensure_bootstrap_admin(session) is None
    assert session.added == []


async def test_an_existing_user_blocks_creation(monkeypatch):
    """The whole safety argument. If anyone exists, this is inert."""
    monkeypatch.setattr(settings, "bootstrap_admin_email", "admin@awdtech.co.za")
    session = FakeSession(user_count=1)
    assert await ensure_bootstrap_admin(session) is None
    assert session.added == []
    assert not session.committed


async def test_the_first_user_is_created_as_a_staff_platform_admin(monkeypatch):
    monkeypatch.setattr(settings, "bootstrap_admin_email", "admin@awdtech.co.za")
    monkeypatch.setattr(settings, "bootstrap_admin_password", "a-long-enough-password")
    session = FakeSession(user_count=0)

    assert await ensure_bootstrap_admin(session) == "admin@awdtech.co.za"
    user = session.added[0]
    assert user.role == "platform_admin"
    assert user.is_staff is True
    assert user.tenant_id is None, "staff must not be scoped to a tenant"
    assert session.committed


async def test_the_password_is_hashed_never_stored_raw(monkeypatch):
    monkeypatch.setattr(settings, "bootstrap_admin_email", "admin@awdtech.co.za")
    monkeypatch.setattr(settings, "bootstrap_admin_password", "a-long-enough-password")
    session = FakeSession(user_count=0)
    await ensure_bootstrap_admin(session)

    from app.security import verify_password

    user = session.added[0]
    assert "a-long-enough-password" not in user.password_hash
    assert verify_password("a-long-enough-password", user.password_hash)


async def test_a_short_password_is_replaced_rather_than_accepted(monkeypatch):
    """A weak password on a public-facing platform_admin is worse than an
    inconvenient one the operator has to read out of the logs."""
    monkeypatch.setattr(settings, "bootstrap_admin_email", "admin@awdtech.co.za")
    monkeypatch.setattr(settings, "bootstrap_admin_password", "short")
    session = FakeSession(user_count=0)
    await ensure_bootstrap_admin(session)

    from app.security import verify_password

    assert not verify_password("short", session.added[0].password_hash)


async def test_a_concurrent_replica_losing_the_race_is_not_an_error(monkeypatch):
    from sqlalchemy.exc import IntegrityError

    monkeypatch.setattr(settings, "bootstrap_admin_email", "admin@awdtech.co.za")
    session = FakeSession(user_count=0)

    async def conflict():
        raise IntegrityError("insert", {}, Exception("duplicate email"))

    session.commit = conflict
    assert await ensure_bootstrap_admin(session) is None
    assert session.rolled_back
