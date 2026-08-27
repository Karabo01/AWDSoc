"""Fingerprinting and the attach/create decision.

Grouping is deliberately coarse. An analyst covering six clients would rather
open one incident with forty alerts than forty incidents.
"""

import uuid

from app.incidents.grouping import fingerprint, primary_entity


def test_the_tenant_is_inside_the_hash():
    """Two clients can never share an incident, whatever else matches."""
    a = fingerprint(tenant_id=uuid.uuid4(), rule_id=5710, agent_id="001")
    b = fingerprint(tenant_id=uuid.uuid4(), rule_id=5710, agent_id="001")
    assert a != b


def test_the_same_facts_always_hash_the_same():
    tenant = uuid.uuid4()
    args = dict(tenant_id=tenant, rule_id=5710, agent_id="001", primary_entity="41.1.2.3")
    assert fingerprint(**args) == fingerprint(**args)


def test_a_uuid_and_its_string_form_agree():
    """The consumer passes a UUID; the reprocess task passes whatever the row
    holds. A mismatch would silently re-home every alert it touched."""
    tenant = uuid.uuid4()
    assert fingerprint(tenant_id=tenant, rule_id=1, agent_id="a") == fingerprint(
        tenant_id=str(tenant), rule_id=1, agent_id="a"
    )


def test_different_rules_group_separately():
    tenant = uuid.uuid4()
    assert fingerprint(tenant_id=tenant, rule_id=5710, agent_id="1") != fingerprint(
        tenant_id=tenant, rule_id=5712, agent_id="1"
    )


def test_different_agents_group_separately():
    tenant = uuid.uuid4()
    assert fingerprint(tenant_id=tenant, rule_id=1, agent_id="001") != fingerprint(
        tenant_id=tenant, rule_id=1, agent_id="002"
    )


def test_a_missing_agent_is_stable_rather_than_random():
    tenant = uuid.uuid4()
    assert fingerprint(tenant_id=tenant, rule_id=1, agent_id=None) == fingerprint(
        tenant_id=tenant, rule_id=1, agent_id=""
    )


# --- primary entity -----------------------------------------------------------


def test_source_ip_wins_first():
    assert primary_entity({"source.ip": "41.1.2.3", "user.name": "admin"}) == "41.1.2.3"


def test_user_name_is_next():
    assert primary_entity({"user.name": "admin", "host.name": "web01"}) == "admin"


def test_host_name_is_last():
    assert primary_entity({"host.name": "web01"}) == "web01"


def test_an_empty_document_yields_an_empty_entity():
    assert primary_entity({}) == ""


def test_a_list_valued_field_is_skipped_rather_than_stringified():
    """A list would stringify differently across runs and split one incident
    into many."""
    assert primary_entity({"source.ip": ["a", "b"], "user.name": "admin"}) == "admin"


def test_the_fingerprint_changes_when_the_primary_entity_does():
    """This is why reprocessing after a map change matters before M5 data
    exists: normalisation feeds the primary entity, which feeds grouping."""
    tenant = uuid.uuid4()
    assert fingerprint(
        tenant_id=tenant, rule_id=1, agent_id="1", primary_entity=""
    ) != fingerprint(tenant_id=tenant, rule_id=1, agent_id="1", primary_entity="41.1.2.3")
