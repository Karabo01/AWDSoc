"""Normalisation is the highest-value test surface in the product.

Field by field against a fixture corpus, one file per decoder family. Every
mapping bug found in production becomes a fixture here.
"""

import json
import pathlib

import pytest

from app.normalisation.engine import load_map, normalise, resolve
from app.normalisation.pipeline import normalise_alert

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "alerts"
VERSION = 1


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def ecs(name: str) -> dict:
    return normalise(fixture(name), version=VERSION)


# --- the map itself -----------------------------------------------------------


def test_the_map_loads_and_declares_its_own_version():
    assert load_map(VERSION).version == VERSION


def test_an_unknown_map_version_fails_loudly():
    with pytest.raises(FileNotFoundError):
        load_map(999)


def test_the_map_is_global_not_per_tenant():
    """Per-tenant maps fragment the entity model and make the pivot useless."""
    maps_dir = FIXTURES.parents[2] / "app" / "normalisation" / "maps"
    assert sorted(p.name for p in maps_dir.glob("*.yaml")) == ["v1.yaml"]


# --- path resolution ----------------------------------------------------------


def test_a_dotted_path_walks_nested_objects():
    assert resolve({"a": {"b": {"c": 1}}}, "a.b.c") == 1


def test_a_missing_path_is_none_not_an_error():
    assert resolve({"a": {}}, "a.b.c") is None


def test_a_wrong_type_mid_path_is_absent_not_an_exception():
    """A decoder can put anything anywhere. That must never be an exception."""
    assert resolve({"a": "string"}, "a.b") is None
    assert resolve({"a": 5}, "a.b.c") is None


def test_a_list_mid_path_takes_the_first_element_that_continues_it():
    assert resolve({"a": [{"x": 1}, {"b": 2}]}, "a.b") == 2


# --- Windows security ---------------------------------------------------------


def test_windows_logon_failure_maps_user_and_address():
    document = ecs("windows_security_4625")
    assert document["source.ip"] == "41.72.14.9"
    assert document["source.port"] == "51422"
    assert document["user.name"] == "Administrator"
    assert document["host.name"] == "DC01"
    assert document["event.severity"] == 5


def test_the_windows_override_prefers_the_event_id_over_the_rule_id():
    """`event.code` defaults to rule.id, but for Windows the analyst means 4625."""
    assert ecs("windows_security_4625")["event.code"] == "4625"
    assert ecs("windows_security_4625")["event.provider"] == (
        "Microsoft-Windows-Security-Auditing"
    )


def test_mitre_ids_survive_as_lists():
    document = ecs("windows_security_4625")
    assert document["threat.technique.id"] == ["T1110"]
    assert document["threat.tactic.name"] == ["Credential Access"]


# --- syscheck -----------------------------------------------------------------


def test_syscheck_maps_path_and_every_hash():
    document = ecs("syscheck_modified")
    assert document["file.path"] == "/etc/ssh/sshd_config"
    assert document["file.hash.sha256"].startswith("9f86d081")
    assert document["file.hash.sha1"] == "356a192b7913b04c54574d18c28d46e6395428ab"
    assert document["file.hash.md5"] == "d41d8cd98f00b204e9800998ecf8427e"


def test_the_syscheck_override_sets_a_constant_category():
    assert ecs("syscheck_modified")["event.category"] == "file"


# --- Office 365 ---------------------------------------------------------------


def test_office365_maps_workload_operation_and_client_address():
    document = ecs("office365")
    assert document["event.provider"] == "AzureActiveDirectory"
    assert document["event.action"] == "UserLoggedIn"
    assert document["user.name"] == "jsmith@acme.co.za"
    assert document["source.ip"] == "102.65.200.14"


def test_an_override_beats_the_default_for_the_same_field():
    """event.action defaults to rule.description; office365 overrides it to the
    actual operation."""
    assert ecs("office365")["event.action"] != fixture("office365")["rule"]["description"]


# --- FortiGate ----------------------------------------------------------------


def test_fortigate_maps_both_endpoints_and_the_protocol():
    document = ecs("fortigate")
    assert document["source.ip"] == "185.220.101.44"
    assert document["destination.ip"] == "10.20.0.31"
    assert document["network.protocol"] == "6"
    assert document["event.provider"] == "fortigate"


# --- AWS ----------------------------------------------------------------------


def test_aws_maps_identity_region_and_account():
    document = ecs("aws_cloudtrail")
    assert document["source.ip"] == "196.10.52.7"
    assert document["user.name"] == "deploy-bot"
    assert document["cloud.region"] == "af-south-1"
    assert document["cloud.account.id"] == "123456789012"


# --- failure mode -------------------------------------------------------------


def test_a_malformed_decoder_never_drops_the_alert():
    """DESIGN.md §5: log it, write ecs = {} and map_version = -1, and continue."""
    result = normalise_alert(fixture("malformed_decoder"), version=VERSION)
    assert not result.failed, "this fixture should degrade gracefully, not throw"
    assert result.map_version == VERSION


def test_a_map_that_cannot_be_loaded_marks_the_row_rather_than_raising():
    result = normalise_alert({"id": "x"}, version=999)
    assert result.failed
    assert result.map_version == -1
    assert result.ecs == {}


def test_normalisation_never_raises_on_hostile_input():
    for hostile in (
        {},
        {"rule": None},
        {"rule": {"groups": "not-a-list"}},
        {"data": {"srcip": {"nested": "object"}}},
        {"agent": "string"},
        {"rule": {"mitre": []}},
    ):
        normalise_alert(hostile, version=VERSION)


def test_empty_values_are_omitted_rather_than_stored_as_null():
    """A key present with a null value would defeat `ecs @> ...` containment."""
    document = normalise(
        {"rule": {"level": 5, "id": "1"}, "data": {"srcip": ""}}, version=VERSION
    )
    assert "source.ip" not in document
    assert all(v not in (None, "", [], {}) for v in document.values())
