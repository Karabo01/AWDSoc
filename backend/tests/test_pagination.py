"""Keyset cursors.

Offset pagination on a table growing by thousands of rows an hour produces
duplicate and skipped rows while an analyst is paging through it.
"""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from app.pagination import decode_cursor, encode_cursor


def test_a_cursor_round_trips():
    when = datetime(2026, 8, 27, 9, 15, tzinfo=UTC)
    row_id = uuid.uuid4()
    assert decode_cursor(encode_cursor(when, row_id)) == (when, row_id)


def test_a_cursor_survives_url_encoding():
    """Cursors travel in a query string, so the alphabet must be URL-safe."""
    token = encode_cursor(datetime.now(UTC), uuid.uuid4())
    assert "+" not in token and "/" not in token


@pytest.mark.parametrize(
    "bad", ["", "not-base64!", "YWJj", "!!!!", "MjAyNi0wOC0yN3xub3QtYS11dWlk"]
)
def test_a_tampered_cursor_is_a_400_not_a_500(bad):
    with pytest.raises(HTTPException) as exc:
        decode_cursor(bad)
    assert exc.value.status_code == 400


def test_the_cursor_carries_both_sort_keys():
    """Timestamp alone is not unique: alerts arrive in bursts sharing a
    millisecond, and a cursor on time alone would skip or repeat them."""
    when = datetime(2026, 8, 27, 9, 15, tzinfo=UTC)
    a, b = encode_cursor(when, uuid.uuid4()), encode_cursor(when, uuid.uuid4())
    assert a != b
