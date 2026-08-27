"""`related.*` is the entire basis of the entity pages.

Without these arrays you have an alert list; with them you have a pivotable
graph. The pivot only works if extraction is generous about role and strict about
validity - `related_ip` is an `inet[]`, so one bad value fails the whole insert.
"""

import json
import pathlib

from app.normalisation.engine import load_map, normalise
from app.normalisation.pipeline import normalise_alert
from app.normalisation.related import as_hash, as_ip, extract

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "alerts"
VERSION = 1


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def related(name: str) -> dict:
    alert = fixture(name)
    document = normalise(alert, version=VERSION)
    rule = alert.get("rule")
    groups = rule.get("groups") if isinstance(rule, dict) else None
    return extract(document, alert, load_map(VERSION), rule_groups=groups)


# --- addresses ----------------------------------------------------------------


def test_source_and_destination_land_in_one_array_regardless_of_role():
    """An address that was the source in one alert and the destination in another
    is the same entity, and the pivot must find both."""
    ips = related("fortigate")["related_ip"]
    assert "185.220.101.44" in ips
    assert "10.20.0.31" in ips


def test_the_agent_address_is_always_collected():
    assert "10.20.0.10" in related("windows_security_4625")["related_ip"]


def test_addresses_buried_in_full_log_are_swept_for_allowlisted_groups():
    """The sshd group is on the allowlist, so the attacker address in the log
    line is recovered even though the decoder also gave it to us."""
    ips = related("sshd_bruteforce")["related_ip"]
    assert "45.155.205.233" in ips


def test_full_log_is_not_swept_for_groups_outside_the_allowlist():
    """A regex sweep over every alert would be expensive and noisy."""
    alert = fixture("windows_security_4625")
    alert["full_log"] = "an unrelated address 203.0.113.55 appears here"
    document = normalise(alert, version=VERSION)
    result = extract(document, alert, load_map(VERSION), rule_groups=alert["rule"]["groups"])
    assert "203.0.113.55" not in result["related_ip"]


def test_loopback_is_not_an_entity():
    assert as_ip("127.0.0.1") is None
    assert as_ip("::1") is None
    assert as_ip("0.0.0.0") is None


def test_private_addresses_are_kept():
    """10.x is exactly what an analyst pivots on during lateral movement."""
    assert as_ip("10.20.0.31") == "10.20.0.31"
    assert as_ip("192.168.1.5") == "192.168.1.5"


def test_an_address_with_a_port_suffix_still_resolves():
    assert as_ip("41.72.14.9:51422") == "41.72.14.9"


def test_junk_is_never_offered_to_an_inet_column():
    """One bad value fails the whole batch insert, so this is load-bearing."""
    for junk in ("not-an-address", "999.1.1.1", "", "-", "1.2.3", "version 4.9.0"):
        assert as_ip(junk) is None


def test_every_extracted_address_is_parseable():
    import ipaddress

    for name in ("fortigate", "sshd_bruteforce", "office365", "windows_security_4625"):
        for value in related(name)["related_ip"]:
            ipaddress.ip_address(value)


# --- users --------------------------------------------------------------------


def test_usernames_are_collected_from_named_fields():
    assert "Administrator" in related("windows_security_4625")["related_user"]
    assert "jsmith@acme.co.za" in related("office365")["related_user"]


def test_usernames_dedupe_case_insensitively_but_keep_the_observed_spelling():
    mapping = load_map(VERSION)
    document = {"user.name": ["Administrator", "administrator", "ADMINISTRATOR"]}
    users = extract(document, {}, mapping)["related_user"]
    assert users == ["Administrator"]


def test_placeholder_usernames_are_dropped():
    mapping = load_map(VERSION)
    document = {"user.name": ["-", "N/A", "(null)", "", "realuser"]}
    assert extract(document, {}, mapping)["related_user"] == ["realuser"]


# --- hosts --------------------------------------------------------------------


def test_the_agent_name_is_always_a_host():
    assert "DC01" in related("windows_security_4625")["related_host"]
    assert "web01" in related("sshd_bruteforce")["related_host"]


# --- hashes -------------------------------------------------------------------


def test_every_hash_length_is_recognised():
    assert as_hash("d41d8cd98f00b204e9800998ecf8427e")  # md5
    assert as_hash("356a192b7913b04c54574d18c28d46e6395428ab")  # sha1
    assert as_hash("9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08")


def test_hashes_are_lowercased_for_matching():
    assert as_hash("D41D8CD98F00B204E9800998ECF8427E") == (
        "d41d8cd98f00b204e9800998ecf8427e"
    )


def test_a_non_hash_hex_string_of_the_wrong_length_is_not_a_hash():
    assert as_hash("deadbeef") is None
    assert as_hash("not-hex-at-all-but-32-characters") is None


def test_syscheck_hashes_all_reach_the_pivot():
    hashes = related("syscheck_modified")["related_hash"]
    assert len(hashes) == 3
    assert all(h == h.lower() for h in hashes)


# --- the whole pipeline -------------------------------------------------------


def test_a_malformed_alert_yields_empty_arrays_rather_than_failing():
    result = normalise_alert(fixture("malformed_decoder"), version=VERSION)
    assert result.related_ip == []
    assert result.related_user == []


def test_arrays_are_ordered_and_free_of_duplicates():
    for name in ("fortigate", "sshd_bruteforce", "syscheck_modified"):
        result = related(name)
        for key, values in result.items():
            assert len(values) == len({v.lower() for v in values}), key
