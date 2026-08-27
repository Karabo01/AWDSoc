"""Credentials must not leak through the API surface.

DESIGN.md §13: `password_enc` must never appear in any serialised API response.
This walks the generated OpenAPI schema rather than a list of endpoints, so a new
route that returns a tenant or connection object cannot quietly regress it.
"""

from app.main import app

# The one write-once payload allowed to carry an ingest secret. Named so that a
# reviewer seeing it in a diff looks twice.
SECRET_BEARING_MODELS = {"TenantSecretRevealed"}

# The one response model allowed to carry a password, for the same write-once
# reason: a generated credential has to be shown once or it is unusable, and the
# console has no mail path to send it down instead. Both user creation and
# password reset return this single shape so there is exactly one to watch.
PASSWORD_BEARING_MODELS = {"UserCreated"}

FORBIDDEN_SUBSTRINGS = ("password", "secret", "ingest_secret")


def _schemas() -> dict:
    return app.openapi().get("components", {}).get("schemas", {})


def test_password_never_appears_in_any_response_model():
    offenders = []
    for name, schema in _schemas().items():
        for field in schema.get("properties", {}):
            if "password" in field.lower():
                offenders.append(f"{name}.{field}")
    # Request models legitimately accept a password; response models must not
    # return one. Anything named *In/*Update/*Create is inbound.
    inbound = tuple(("In", "Update", "Create", "Request"))
    leaks = [
        o
        for o in offenders
        if not o.split(".")[0].endswith(inbound)
        and o.split(".")[0] not in PASSWORD_BEARING_MODELS
    ]
    assert leaks == [], f"password fields on response models: {leaks}"


def test_the_write_once_password_model_is_the_only_exception():
    """Guards the allowlist above.

    Adding a name to `PASSWORD_BEARING_MODELS` silences the test for that model,
    so the allowlist itself is asserted: it must stay at exactly one entry, and
    that entry must still exist in the schema. Growing it is then a deliberate
    edit to this assertion rather than a quiet addition to a set.
    """
    assert PASSWORD_BEARING_MODELS == {"UserCreated"}
    assert "password" in _schemas()["UserCreated"].get("properties", {})


def test_password_enc_is_not_in_the_schema_at_all():
    for name, schema in _schemas().items():
        assert "password_enc" not in schema.get("properties", {}), name


def test_ingest_secret_appears_only_in_the_write_once_payload():
    carriers = {
        name
        for name, schema in _schemas().items()
        if "ingest_secret" in schema.get("properties", {})
    }
    assert carriers <= SECRET_BEARING_MODELS, (
        f"unexpected models expose ingest_secret: {carriers - SECRET_BEARING_MODELS}"
    )


def test_the_tenant_read_model_carries_no_credential_of_any_kind():
    properties = _schemas()["TenantRead"].get("properties", {})
    for field in properties:
        assert not any(bad in field.lower() for bad in FORBIDDEN_SUBSTRINGS), field


def test_the_connection_read_model_carries_no_credential_of_any_kind():
    properties = _schemas()["WazuhConnectionRead"].get("properties", {})
    assert "base_url" in properties  # guards against an empty-schema false pass
    for field in properties:
        assert not any(bad in field.lower() for bad in FORBIDDEN_SUBSTRINGS), field


def test_the_schema_component_set_is_not_empty():
    """Guards every assertion above: an empty schema would make them vacuous."""
    assert "TenantRead" in _schemas()
