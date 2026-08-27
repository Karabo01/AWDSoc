"""Cursor pagination.

Offset pagination on a table growing by thousands of rows an hour produces
duplicate and skipped rows while an analyst pages through it. Every list endpoint
over `alerts` or `incidents` uses a keyset cursor on (timestamp, id) instead.
"""

import base64
import binascii
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import HTTPException, status

BAD_CURSOR = HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST,
    detail="That page cursor is not valid. Start from the first page.",
)

KeyKind = Literal["datetime", "int"]


def encode_cursor(timestamp: datetime, row_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(f"{timestamp.isoformat()}|{row_id}".encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        timestamp, _, row_id = raw.partition("|")
        return datetime.fromisoformat(timestamp), uuid.UUID(row_id)
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That page cursor is not valid. Start from the first page.",
        ) from exc


def encode_key_cursor(value: Any, row_id: uuid.UUID) -> str:
    """Cursor for a sort on something other than a timestamp.

    A sortable grid means the keyset changes with the column, so the cursor has
    to carry whatever that column holds. The sort key is always sent alongside
    the cursor, so the reader knows how to parse this back - the cursor itself
    stays opaque and is never trusted to name its own type.
    """
    raw = value.isoformat() if isinstance(value, datetime) else str(value)
    return base64.urlsafe_b64encode(f"{raw}|{row_id}".encode()).decode()


def decode_key_cursor(cursor: str, kind: KeyKind) -> tuple[Any, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        key, _, row_id = raw.partition("|")
        parsed = datetime.fromisoformat(key) if kind == "datetime" else int(key)
        return parsed, uuid.UUID(row_id)
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise BAD_CURSOR from exc
