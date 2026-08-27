"""The mapping engine.

The map is data (maps/v1.yaml); this file is the interpreter. It is global rather
than per-tenant on purpose: onboarding a client with an unusual decoder extends
the shared map and every tenant benefits.

Normalisation runs platform-side, never in a decoder and never in an OpenSearch
ingest pipeline. Client Wazuh instances sit at different versions and get
upgraded without telling us; the console's schema must not be collateral.
"""

import functools
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

MAPS_DIR = Path(__file__).parent / "maps"


@dataclass(frozen=True)
class FieldSpec:
    """Either a list of source paths (first non-null wins) or a constant."""

    paths: tuple[str, ...] = ()
    const: Any = None
    is_const: bool = False


@dataclass
class Override:
    match_groups: frozenset[str]
    fields: dict[str, FieldSpec]


@dataclass
class Mapping:
    version: int
    defaults: dict[str, FieldSpec]
    overrides: list[Override] = field(default_factory=list)
    user_fields: tuple[str, ...] = ()
    host_fields: tuple[str, ...] = ()
    full_log_ip_scan_groups: frozenset[str] = frozenset()


def _parse_field_spec(raw: Any) -> FieldSpec:
    if isinstance(raw, dict):
        if "const" not in raw:
            raise ValueError(f"field spec dict must carry 'const', got {raw!r}")
        return FieldSpec(const=raw["const"], is_const=True)
    if isinstance(raw, str):
        return FieldSpec(paths=(raw,))
    if isinstance(raw, list):
        return FieldSpec(paths=tuple(str(p) for p in raw))
    raise ValueError(f"unsupported field spec: {raw!r}")


def _parse(document: dict) -> Mapping:
    related = document.get("related") or {}
    return Mapping(
        version=int(document["version"]),
        defaults={
            name: _parse_field_spec(spec)
            for name, spec in (document.get("defaults") or {}).items()
        },
        overrides=[
            Override(
                match_groups=frozenset(entry.get("match_groups") or []),
                fields={
                    name: _parse_field_spec(spec)
                    for name, spec in (entry.get("fields") or {}).items()
                },
            )
            for entry in (document.get("overrides") or [])
        ],
        user_fields=tuple(related.get("user_fields") or []),
        host_fields=tuple(related.get("host_fields") or []),
        full_log_ip_scan_groups=frozenset(related.get("full_log_ip_scan_groups") or []),
    )


@functools.lru_cache(maxsize=8)
def load_map(version: int) -> Mapping:
    path = MAPS_DIR / f"v{version}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"no normalisation map for version {version} at {path}")
    with path.open(encoding="utf-8") as handle:
        mapping = _parse(yaml.safe_load(handle))
    if mapping.version != version:
        raise ValueError(
            f"{path.name} declares version {mapping.version}, expected {version}"
        )
    return mapping


def resolve(alert: dict, path: str) -> Any:
    """Walk a dotted path into the raw alert.

    Tolerant by design: a decoder can put anything anywhere, and a wrong type
    mid-path means "absent", never an exception. Where a list is encountered the
    first element that continues the path wins, so `data.items.name` works
    whether `items` is an object or a one-element array.
    """
    current: Any = alert
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            found = None
            for item in current:
                if isinstance(item, dict) and part in item:
                    found = item[part]
                    break
            current = found
        else:
            return None
        if current is None:
            return None
    return current


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _apply(spec: FieldSpec, alert: dict) -> Any:
    if spec.is_const:
        return spec.const
    for path in spec.paths:
        value = resolve(alert, path)
        if not _is_empty(value):
            return value
    return None


def normalise(alert: dict, *, version: int) -> dict:
    """Raw Wazuh alert -> flat ECS document.

    Returns dotted keys, not nested objects: it keeps a containment query a
    single GIN lookup, and keeps the stored document readable as the same shape
    as the map that produced it.
    """
    mapping = load_map(version)

    groups = alert.get("rule", {}).get("groups") if isinstance(alert.get("rule"), dict) else None
    groups = frozenset(groups) if isinstance(groups, list) else frozenset()

    specs: dict[str, FieldSpec] = dict(mapping.defaults)
    for override in mapping.overrides:
        if override.match_groups & groups:
            specs.update(override.fields)

    document: dict[str, Any] = {}
    for name, spec in specs.items():
        value = _apply(spec, alert)
        if not _is_empty(value):
            document[name] = value
    return document
