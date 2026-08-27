"""Everything the client's manager needs, generated from the tenant row.

Onboarding is meant to be a form plus one command, so the console produces the
exact `<integration>` block and installer invocation rather than leaving an
engineer to assemble them from the docs.
"""

import secrets

from app.config import settings

# Quiet per-tenant hues for the 3px left border on queue rows. Colour never
# carries tenant identity alone - the chip is always present - so these only
# need to be distinguishable, not accessible on their own.
TENANT_COLOURS = [
    "#4C8DF6",
    "#37B3A0",
    "#B98BE8",
    "#E8A13B",
    "#E0657F",
    "#6FBF5B",
    "#54A8C7",
    "#C9805A",
]


def generate_ingest_secret() -> str:
    return secrets.token_urlsafe(32)


def pick_colour(taken: list[str | None]) -> str:
    """First unused hue, wrapping once every tenant has one."""
    used = {c for c in taken if c}
    for colour in TENANT_COLOURS:
        if colour not in used:
            return colour
    return TENANT_COLOURS[len(used) % len(TENANT_COLOURS)]


def ingest_url(slug: str) -> str:
    return f"{settings.console_base_url.rstrip('/')}/api/v1/ingest/wazuh/{slug}"


def integration_block(slug: str, secret: str, *, alert_floor: int, group: str | None) -> str:
    """The block for the client's /var/ossec/etc/ossec.conf.

    On a shared manager the `<group>` filter is the only thing routing this
    tenant's alerts to this tenant's URL, so it is never optional there.
    """
    group_line = f"  <group>{group}</group>\n" if group else ""
    return (
        "<integration>\n"
        "  <name>custom-awd-console</name>\n"
        f"  <hook_url>{ingest_url(slug)}</hook_url>\n"
        f"  <api_key>{secret}</api_key>\n"
        f"{group_line}"
        f"  <level>{alert_floor}</level>\n"
        "  <alert_format>json</alert_format>\n"
        "</integration>"
    )


def install_command(slug: str, secret: str, *, alert_floor: int, group: str | None) -> str:
    group_arg = f" --group {group}" if group else ""
    return (
        f"sudo ./install.sh --slug {slug} --secret {secret} "
        f"--url {settings.console_base_url.rstrip('/')} --level {alert_floor}{group_arg}"
    )
