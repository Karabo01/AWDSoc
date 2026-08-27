"""Parsing must never raise. A malformed decoder on one client must not stop the
pipeline for every client - `raw` is preserved regardless, so a bad parse is
recoverable by replay."""

from datetime import UTC, datetime

import pytest

from app.ingest.parser import NOT_NORMALISED, parse, parse_timestamp

ALERT = {
    "id": "1756252800.123456",
    "timestamp": "2026-08-27T09:15:00.123+0000",
    "rule": {
        "level": 10,
        "id": "5710",
        "description": "SSH brute force",
        "groups": ["syslog", "sshd", "authentication_failed"],
        "mitre": {"id": ["T1110"], "tactic": ["Credential Access"]},
    },
    "agent": {"id": "001", "name": "web01", "ip": "10.0.0.5"},
}


def test_a_normal_alert_parses_completely():
    parsed = parse(ALERT)
    assert parsed.wazuh_id == "1756252800.123456"
    assert parsed.rule_id == 5710
    assert parsed.rule_level == 10
    assert parsed.rule_desc == "SSH brute force"
    assert parsed.rule_groups == ["syslog", "sshd", "authentication_failed"]
    assert parsed.mitre_ids == ["T1110"]
    assert parsed.mitre_tactics == ["Credential Access"]
    assert parsed.agent_id == "001"
    assert parsed.agent_name == "web01"
    assert parsed.timestamp.tzinfo is not None


def test_the_rule_id_is_coerced_from_wazuhs_string_form():
    assert parse(ALERT).rule_id == 5710
    assert isinstance(parse(ALERT).rule_id, int)


@pytest.mark.parametrize(
    "value",
    [
        "2026-08-27T09:15:00.123+0000",
        "2026-08-27T09:15:00+00:00",
        "2026-08-27T09:15:00Z",
        "2026-08-27T09:15:00.123456+02:00",
    ],
)
def test_the_wazuh_timestamp_forms_all_parse(value):
    parsed = parse_timestamp(value)
    assert parsed is not None and parsed.tzinfo is not None


def test_a_naive_timestamp_is_assumed_utc():
    assert parse_timestamp("2026-08-27T09:15:00").tzinfo is UTC


def test_an_unparseable_timestamp_falls_back_to_receipt_time():
    received = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    parsed = parse({**ALERT, "timestamp": "not a date"}, received_at=received)
    assert parsed.timestamp == received


def test_a_missing_timestamp_falls_back_rather_than_raising():
    received = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    alert = {k: v for k, v in ALERT.items() if k != "timestamp"}
    assert parse(alert, received_at=received).timestamp == received


def test_an_empty_alert_still_produces_a_writable_row():
    parsed = parse({})
    assert parsed.wazuh_id
    assert parsed.rule_id == 0
    assert parsed.rule_level == 0
    assert parsed.rule_desc == "(no description)"
    assert parsed.agent_id is None


def test_a_missing_alert_id_gets_a_deterministic_substitute():
    """Without one the unique constraint cannot dedup, so we synthesise from the
    timestamp rather than dropping the alert."""
    alert = {k: v for k, v in ALERT.items() if k != "id"}
    first, second = parse(alert), parse(alert)
    assert first.wazuh_id == second.wazuh_id
    assert first.wazuh_id.startswith("noid-")


def test_a_rule_level_outside_the_ramp_is_clamped():
    assert parse({**ALERT, "rule": {**ALERT["rule"], "level": 99}}).rule_level == 15
    assert parse({**ALERT, "rule": {**ALERT["rule"], "level": -4}}).rule_level == 0


def test_a_scalar_mitre_id_is_accepted_as_well_as_a_list():
    alert = {**ALERT, "rule": {**ALERT["rule"], "mitre": {"id": "T1110"}}}
    assert parse(alert).mitre_ids == ["T1110"]


def test_junk_types_do_not_raise():
    for junk in ({"rule": "not-an-object"}, {"agent": []}, {"rule": {"groups": 42}}):
        parse({**ALERT, **junk})


def test_m3_marks_rows_as_not_yet_normalised():
    """0 means "M4 has not run"; -1 means "normalisation threw". Conflating them
    would make the reprocess endpoint unable to tell them apart."""
    assert NOT_NORMALISED == 0
    from app.ingest.parser import NORMALISATION_FAILED

    assert NORMALISATION_FAILED == -1
