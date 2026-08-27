"""Evidence snapshots are what make 90-day retention survivable.

Member alerts vanish at 90 days; a resolved case from four months ago must still
show what it was about.
"""

import json
from datetime import UTC, datetime

from app.incidents import evidence

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def fold(snapshot, *, ecs=None, related=None, is_first=False, level=10):
    return evidence.update(
        snapshot,
        ecs=ecs or {"source.ip": "41.1.2.3", "user.name": "admin"},
        related=related or {"related_ip": ["41.1.2.3"]},
        timestamp=NOW,
        rule_desc="SSH brute force",
        rule_level=level,
        is_first=is_first,
    )


def test_the_first_alert_is_captured_and_never_overwritten():
    snapshot = fold({}, is_first=True, ecs={"source.ip": "1.1.1.1"})
    snapshot = fold(snapshot, ecs={"source.ip": "2.2.2.2"})
    assert snapshot["first"]["ecs"]["source.ip"] == "1.1.1.1"
    assert snapshot["latest"]["ecs"]["source.ip"] == "2.2.2.2"


def test_the_entity_set_accumulates_across_alerts():
    snapshot = fold({}, is_first=True, related={"related_ip": ["1.1.1.1"]})
    snapshot = fold(snapshot, related={"related_ip": ["2.2.2.2"]})
    assert snapshot["entities"]["related_ip"] == ["1.1.1.1", "2.2.2.2"]


def test_entities_do_not_duplicate():
    snapshot = fold({}, is_first=True, related={"related_ip": ["1.1.1.1"]})
    for _ in range(10):
        snapshot = fold(snapshot, related={"related_ip": ["1.1.1.1"]})
    assert snapshot["entities"]["related_ip"] == ["1.1.1.1"]


def test_the_snapshot_stays_under_the_cap_however_many_alerts_attach():
    """An incident with forty alerts must not accumulate forty raw events."""
    snapshot: dict = {}
    for i in range(200):
        snapshot = fold(
            snapshot,
            is_first=(i == 0),
            ecs={f"field.{n}": "x" * 400 for n in range(60)},
            related={"related_ip": [f"10.0.{i // 256}.{i % 256}"]},
        )
    assert len(json.dumps(snapshot).encode()) <= evidence.MAX_BYTES


def test_the_latest_document_is_shed_before_the_first_one():
    """`first` is what an analyst reads in a closed case, so it goes last."""
    big = {f"f{n}": "y" * 500 for n in range(60)}
    snapshot = fold({}, is_first=True, ecs=big)
    snapshot = fold(snapshot, ecs=big, related={"related_ip": ["172.16.0.1"]})

    assert snapshot.get("truncated") is True
    assert snapshot["latest"]["ecs"] == {}
    assert snapshot["first"]["ecs"] != {}, "the first alert must survive longest"
    assert len(json.dumps(snapshot).encode()) <= evidence.MAX_BYTES


def test_an_unbounded_stream_of_alerts_still_fits():
    snapshot: dict = {}
    big = {f"f{n}": "y" * 500 for n in range(60)}
    for i in range(300):
        snapshot = fold(
            snapshot,
            is_first=(i == 0),
            ecs=big,
            related={"related_ip": [f"172.16.{i // 256}.{i % 256}"]},
        )
    assert len(json.dumps(snapshot).encode()) <= evidence.MAX_BYTES
    assert "first" in snapshot


def test_long_string_values_are_clipped_not_dropped():
    snapshot = fold({}, is_first=True, ecs={"process.command_line": "a" * 5000})
    assert len(snapshot["first"]["ecs"]["process.command_line"]) < 600


def test_the_raw_alert_is_never_stored():
    snapshot = fold({}, is_first=True)
    assert "raw" not in json.dumps(snapshot)


def test_a_missing_snapshot_is_treated_as_empty():
    assert evidence.update(
        None,
        ecs={"a": 1},
        related={},
        timestamp=NOW,
        rule_desc="x",
        rule_level=5,
        is_first=True,
    )["first"]["rule_level"] == 5


def test_hostile_ecs_types_do_not_break_the_snapshot():
    for junk in ("string", 42, None, ["list"]):
        fold({}, is_first=True, ecs=junk)
