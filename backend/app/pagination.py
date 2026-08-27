"""Cursor pagination.

Offset pagination on a table growing by thousands of rows an hour produces
duplicate and skipped rows while an analyst pages through it. Every list endpoint
over `alerts` or `incidents` uses a keyset cursor on (timestamp, id) instead.
"""

import base64
import binascii
import uuid
from datetime import datetime

from fastapi import HTTPException, status


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
