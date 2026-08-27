"""Postgres network types crossing the API boundary.

asyncpg returns `inet[]` as IPv4Address objects and `cidr[]` as IPv4Network
objects. Pydantic will not coerce either into `list[str]`, so a response model
exposing one raises at *response* time - after the transaction has committed.
That is how a tenant got created whose creation response 500'd.

These are the shapes a real query produces. Nothing in the pure-Python suite can
generate them, which is exactly why this went undetected until deployment.
"""

import ipaddress
import uuid
from datetime import UTC, datetime

from app.schemas.alert import AlertDetail
from app.schemas.tenant import TenantRead


def test_a_cidr_array_from_asyncpg_serialises():
    tenant = TenantRead.model_validate(
        {
            "id": uuid.uuid4(),
            "slug": "awdtech",
            "name": "AWDTECH",
            "status": "active",
            "alert_floor": 7,
            "grouping_window_minutes": 30,
            "ingest_cidrs": [ipaddress.ip_network("178.18.241.215/32")],
            "colour": "#4C8DF6",
            "created_at": datetime.now(UTC),
        }
    )
    assert tenant.ingest_cidrs == ["178.18.241.215/32"]


def test_an_ipv6_cidr_survives_too():
    tenant = TenantRead.model_validate(
        {
            "id": uuid.uuid4(),
            "slug": "a",
            "name": "A",
            "status": "active",
            "alert_floor": 7,
            "grouping_window_minutes": 30,
            "ingest_cidrs": [ipaddress.ip_network("2001:db8::/32")],
            "colour": None,
            "created_at": datetime.now(UTC),
        }
    )
    assert tenant.ingest_cidrs == ["2001:db8::/32"]


def test_plain_strings_still_work():
    tenant = TenantRead.model_validate(
        {
            "id": uuid.uuid4(),
            "slug": "a",
            "name": "A",
            "status": "active",
            "alert_floor": 7,
            "grouping_window_minutes": 30,
            "ingest_cidrs": ["10.0.0.0/8"],
            "colour": None,
            "created_at": datetime.now(UTC),
        }
    )
    assert tenant.ingest_cidrs == ["10.0.0.0/8"]


def _alert(**overrides):
    base = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "timestamp": datetime.now(UTC),
        "received_at": datetime.now(UTC),
        "wazuh_id": "1.1",
        "rule_id": 5710,
        "rule_level": 10,
        "rule_desc": "x",
        "map_version": 1,
        "fingerprint": "abc",
        "ecs": {},
        "raw": {},
    }
    base.update(overrides)
    return AlertDetail.model_validate(base)


def test_an_inet_array_from_asyncpg_serialises():
    """The same bug was waiting in the alert inspector: `related_ip` is inet[],
    so it would have failed the first time an alert with an address landed."""
    alert = _alert(
        related_ip=[
            ipaddress.ip_address("41.72.14.9"),
            ipaddress.ip_address("2001:db8::5"),
        ]
    )
    assert alert.related_ip == ["41.72.14.9", "2001:db8::5"]


def test_text_arrays_are_untouched():
    alert = _alert(related_user=["Administrator"], related_host=["DC01"])
    assert alert.related_user == ["Administrator"]
    assert alert.related_host == ["DC01"]


def test_an_empty_array_stays_empty():
    assert _alert(related_ip=[]).related_ip == []
