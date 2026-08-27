"""Onboarding is meant to be a form plus one command. These assert the command
the console hands over is the one that actually works."""

from app.config import settings
from app.wazuh.onboarding import (
    TENANT_COLOURS,
    generate_ingest_secret,
    ingest_url,
    install_command,
    integration_block,
    pick_colour,
)


def test_the_ingest_url_addresses_the_tenant_by_slug():
    assert ingest_url("acme-corp") == (
        f"{settings.console_base_url}/api/v1/ingest/wazuh/acme-corp"
    )


def test_secrets_are_long_and_unique():
    secrets = {generate_ingest_secret() for _ in range(50)}
    assert len(secrets) == 50
    assert all(len(s) >= 40 for s in secrets)


def test_a_shared_manager_block_carries_the_group_filter():
    block = integration_block("acme-corp", "SECRET", alert_floor=7, group="acme-corp")
    assert "<group>acme-corp</group>" in block
    assert "<level>7</level>" in block
    assert "/ingest/wazuh/acme-corp" in block


def test_a_dedicated_manager_block_has_no_group_element():
    block = integration_block("acme-corp", "SECRET", alert_floor=7, group=None)
    assert "<group>" not in block


def test_the_alert_floor_reaches_the_manager_so_traffic_never_leaves_it():
    block = integration_block("acme-corp", "SECRET", alert_floor=12, group=None)
    assert "<level>12</level>" in block


def test_the_install_command_passes_the_group_on_a_shared_manager():
    command = install_command("acme-corp", "SECRET", alert_floor=7, group="acme-corp")
    assert "--slug acme-corp" in command
    assert "--secret SECRET" in command
    assert "--group acme-corp" in command


def test_colours_are_assigned_without_collision_until_the_palette_runs_out():
    taken = []
    for _ in range(len(TENANT_COLOURS)):
        colour = pick_colour(taken)
        assert colour not in taken
        taken.append(colour)
    # Wrapping is fine; the tenant chip always carries identity, never colour alone.
    assert pick_colour(taken) in TENANT_COLOURS
