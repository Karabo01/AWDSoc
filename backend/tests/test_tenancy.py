import uuid

import pytest
from fastapi import HTTPException

from app.deps.tenancy import TenantScope
from app.security import TokenClaims


def claims(**kw) -> TokenClaims:
    from datetime import UTC, datetime

    base = dict(
        user_id=uuid.uuid4(),
        role="soc_analyst",
        is_staff=True,
        tenant_id=None,
        active_tenant=None,
        token_type="access",
        jti="j",
        expires_at=datetime.now(UTC),
    )
    base.update(kw)
    return TokenClaims(**base)


def test_client_scope_is_its_own_tenant_and_owns_nothing_else():
    tenant, other = uuid.uuid4(), uuid.uuid4()
    scope = TenantScope(
        claims(is_staff=False, role="client_admin", tenant_id=tenant)
    )
    assert not scope.is_fleet_view
    assert scope.owns(tenant)
    assert not scope.owns(other)


def test_staff_fleet_view_owns_every_tenant():
    scope = TenantScope(claims())
    assert scope.is_fleet_view
    assert scope.owns(uuid.uuid4())


def test_staff_narrowed_to_one_tenant_owns_only_that_one():
    tenant = uuid.uuid4()
    scope = TenantScope(claims(active_tenant=tenant))
    assert not scope.is_fleet_view
    assert scope.owns(tenant)
    assert not scope.owns(uuid.uuid4())


def test_a_tenantless_client_token_is_refused_not_widened():
    with pytest.raises(HTTPException) as exc:
        TenantScope(claims(is_staff=False, role="client_viewer", tenant_id=None))
    assert exc.value.status_code == 403
