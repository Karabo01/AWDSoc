"""One call, and it never raises.

DESIGN.md §5: normalisation must never drop an alert. If extraction throws, log
it, write the row with `ecs = {}` and `map_version = -1`, and continue. A
malformed decoder on one client must not stop the pipeline for every client.

The count of `map_version = -1` rows per tenant is surfaced on the overview: a
silent failure that nobody looks at is the same as a dropped alert.
"""

import logging
from dataclasses import dataclass, field

from app.config import settings
from app.ingest.parser import NORMALISATION_FAILED
from app.normalisation.engine import load_map, normalise
from app.normalisation.related import extract

log = logging.getLogger(__name__)


@dataclass
class Normalised:
    ecs: dict
    map_version: int
    related_ip: list[str] = field(default_factory=list)
    related_user: list[str] = field(default_factory=list)
    related_host: list[str] = field(default_factory=list)
    related_hash: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return self.map_version == NORMALISATION_FAILED


def normalise_alert(alert: dict, *, version: int | None = None) -> Normalised:
    version = version or settings.normalisation_map_version
    try:
        mapping = load_map(version)
        ecs = normalise(alert, version=version)
        rule = alert.get("rule")
        groups = rule.get("groups") if isinstance(rule, dict) else None
        related = extract(
            ecs,
            alert,
            mapping,
            rule_groups=groups if isinstance(groups, list) else None,
        )
        return Normalised(ecs=ecs, map_version=version, **related)
    except Exception:
        # `raw` is preserved on the row, so every failure here is replayable once
        # the map is fixed. That is the whole point of storing raw verbatim.
        log.exception("normalisation failed for alert %s", alert.get("id"))
        return Normalised(ecs={}, map_version=NORMALISATION_FAILED)
