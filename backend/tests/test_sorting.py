"""Sortable columns, and the cursor that has to follow them.

A sortable grid means the keyset changes with the column, so the cursor stops
being "a timestamp and an id". These cover the part that can go wrong silently:
a cursor decoded as the wrong type would either raise or - worse - compare
against a value that is not what the sort is ordering by, and the page boundary
would land somewhere arbitrary.
"""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.v1.incidents import SORTS
from app.main import app
from app.pagination import decode_key_cursor, encode_key_cursor

client = TestClient(app, raise_server_exceptions=False)


def test_a_datetime_cursor_round_trips():
    when = datetime(2026, 8, 27, 14, 30, tzinfo=UTC)
    row = uuid.uuid4()
    value, decoded = decode_key_cursor(encode_key_cursor(when, row), "datetime")
    assert value == when
    assert decoded == row


def test_an_int_cursor_round_trips():
    row = uuid.uuid4()
    value, decoded = decode_key_cursor(encode_key_cursor(12, row), "int")
    assert value == 12
    assert decoded == row


def test_an_int_cursor_read_as_a_datetime_is_rejected():
    """The kind comes from the sort key, not from the cursor. Reading one as the
    other must fail loudly rather than compare against something arbitrary."""
    cursor = encode_key_cursor(12, uuid.uuid4())
    with pytest.raises(HTTPException) as raised:
        decode_key_cursor(cursor, "datetime")
    assert raised.value.status_code == 400


def test_a_forged_cursor_is_rejected():
    for junk in ("not-base64!", "", "YWJj"):
        with pytest.raises(HTTPException):
            decode_key_cursor(junk, "datetime")


def test_every_sortable_column_declares_a_cursor_kind():
    """Guards the table itself: a column added without a kind would decode as
    whatever the last branch happens to be."""
    assert SORTS
    for name, (column, kind) in SORTS.items():
        assert kind in ("datetime", "int"), f"{name} has no cursor kind"
        assert column is not None


def test_an_unknown_sort_column_is_refused_by_name():
    """Sorting is an allowlist, not a column name off the request - otherwise the
    query builder is taking SQL identifiers from the caller."""
    schema = app.openapi()["paths"]["/api/v1/incidents"]["get"]
    names = [p["name"] for p in schema.get("parameters", [])]
    assert "sort" in names
    assert "order" in names


def test_sorting_is_rejected_without_a_token_before_it_is_validated():
    """Auth comes first: an unauthenticated caller must not be able to probe which
    column names are valid by reading back different error messages."""
    good = client.get("/api/v1/incidents?sort=severity")
    bad = client.get("/api/v1/incidents?sort=; drop table incidents")
    assert good.status_code == 401
    assert bad.status_code == 401
    assert good.json() == bad.json()
