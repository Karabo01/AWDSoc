"""Rule read-through flattening.

The network and cache halves need Redis and Postgres, so what is covered here is
the part that is pure and the part most likely to change under us: the shape
Wazuh returns. Compliance mappings move between a top-level key and a nested
`compliance` object across Wazuh versions, and `mitre` is sometimes absent
entirely, so the flattening has to tolerate all of it without raising.
"""

from app.api.v1.rules import _from_manager


def test_a_modern_manager_payload_is_flattened():
    rule = _from_manager(
        5712,
        {
            "level": 10,
            "description": "sshd: brute force trying to get access to the system",
            "groups": ["syslog", "sshd", "authentication_failures"],
            "mitre": {"id": ["T1110"], "tactic": ["Credential Access"]},
            "compliance": {"pci_dss": ["11.4"], "gdpr": ["IV_35.7.d"]},
            "filename": "0095-sshd_rules.xml",
            "relative_dirname": "ruleset/rules",
        },
    )
    assert rule.id == 5712
    assert rule.level == 10
    assert rule.mitre_ids == ["T1110"]
    assert rule.pci_dss == ["11.4"]
    assert rule.gdpr == ["IV_35.7.d"]
    assert rule.filename == "0095-sshd_rules.xml"
    assert rule.stale is False


def test_compliance_at_the_top_level_is_read_too():
    """Older managers put these beside `level` rather than under `compliance`."""
    rule = _from_manager(100200, {"level": 12, "pci_dss": ["10.6.1"], "hipaa": ["164.312.b"]})
    assert rule.pci_dss == ["10.6.1"]
    assert rule.hipaa == ["164.312.b"]


def test_a_bare_rule_does_not_raise():
    """A custom local rule can carry nothing but a level and a description. The
    case view still has to render."""
    rule = _from_manager(100001, {"level": 3})
    assert rule.id == 100001
    assert rule.mitre_ids == []
    assert rule.groups == []
    assert rule.description is None


def test_a_scalar_where_a_list_was_expected_is_accepted():
    """Wazuh returns a bare string for a single-valued mapping often enough that
    treating it as an error would break real rules."""
    rule = _from_manager(1002, {"groups": "syslog", "mitre": {"id": "T1059"}})
    assert rule.groups == ["syslog"]
    assert rule.mitre_ids == ["T1059"]


def test_a_junk_mitre_block_is_ignored_rather_than_fatal():
    rule = _from_manager(1003, {"mitre": "not-an-object", "compliance": 42})
    assert rule.mitre_ids == []
    assert rule.pci_dss == []
