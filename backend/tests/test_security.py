import uuid

import pytest

from app import security


def test_password_round_trip():
    h = security.hash_password("correct horse battery staple")
    assert security.verify_password("correct horse battery staple", h)
    assert not security.verify_password("wrong", h)


def test_verify_tolerates_a_garbage_hash():
    assert not security.verify_password("anything", "not-a-hash")


def test_staff_token_carries_active_tenant_and_no_fixed_tenant():
    user_id, tenant = uuid.uuid4(), uuid.uuid4()
    token, _ = security.issue_access_token(
        user_id=user_id,
        role="soc_analyst",
        is_staff=True,
        tenant_id=None,
        active_tenant=tenant,
    )
    claims = security.decode_token(token, "access")
    assert claims.is_staff
    assert claims.tenant_id is None
    assert claims.active_tenant == tenant
    assert claims.scope_tenant_id == tenant


def test_staff_fleet_view_scopes_to_no_single_tenant():
    token, _ = security.issue_access_token(
        user_id=uuid.uuid4(),
        role="soc_analyst",
        is_staff=True,
        tenant_id=None,
        active_tenant=None,
    )
    assert security.decode_token(token, "access").scope_tenant_id is None


def test_client_token_scope_ignores_active_tenant():
    tenant, other = uuid.uuid4(), uuid.uuid4()
    token, _ = security.issue_access_token(
        user_id=uuid.uuid4(),
        role="client_viewer",
        is_staff=False,
        tenant_id=tenant,
        active_tenant=other,
    )
    assert security.decode_token(token, "access").scope_tenant_id == tenant


def test_a_refresh_token_is_not_an_access_token():
    token, _, _ = security.issue_refresh_token(
        user_id=uuid.uuid4(), role="platform_admin", is_staff=True, tenant_id=None
    )
    with pytest.raises(security.TokenError):
        security.decode_token(token, "access")


def test_a_token_signed_with_another_secret_is_rejected():
    import jwt

    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "iss": "awdsoc", "typ": "access", "exp": 9999999999,
         "iat": 0, "jti": "x", "role": "platform_admin", "is_staff": True},
        "not-the-secret",
        algorithm="HS256",
    )
    with pytest.raises(security.TokenError):
        security.decode_token(forged, "access")


def test_expired_token_is_rejected():
    from datetime import UTC, datetime

    import jwt

    from app.config import settings

    expired = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "iss": settings.app_name,
            "typ": "access",
            "exp": int(datetime.now(UTC).timestamp()) - 10,
            "iat": 0,
            "jti": "x",
            "role": "soc_analyst",
            "is_staff": True,
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    with pytest.raises(security.TokenError):
        security.decode_token(expired, "access")


def test_refresh_tokens_are_individually_identified():
    a = security.issue_refresh_token(
        user_id=uuid.uuid4(), role="soc_analyst", is_staff=True, tenant_id=None
    )
    b = security.issue_refresh_token(
        user_id=uuid.uuid4(), role="soc_analyst", is_staff=True, tenant_id=None
    )
    assert a[1] != b[1]
