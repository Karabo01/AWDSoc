"""The image serves two roles from one build.

A worker that silently boots as a second API is the worst kind of failure: the
stack reports healthy, ingest returns 202, and nothing writes to Postgres.
"""

import pathlib
import re

ENTRYPOINT = pathlib.Path(__file__).resolve().parents[1] / "docker-entrypoint.sh"
DOCKERFILE = pathlib.Path(__file__).resolve().parents[1] / "Dockerfile"


def test_the_entrypoint_ships_with_the_image():
    assert ENTRYPOINT.is_file()
    assert "docker-entrypoint.sh" in DOCKERFILE.read_text(encoding="utf-8")


def test_the_dockerfile_runs_the_entrypoint_not_a_hardcoded_command():
    assert 'CMD ["docker-entrypoint.sh"]' in DOCKERFILE.read_text(encoding="utf-8")


def test_both_roles_are_handled():
    script = ENTRYPOINT.read_text(encoding="utf-8")
    assert "uvicorn app.main:app" in script
    assert "arq app.workers.consumer.WorkerSettings" in script


def test_the_default_role_is_api():
    assert "${APP_ROLE:-api}" in ENTRYPOINT.read_text(encoding="utf-8")


def test_an_unknown_role_fails_loudly_rather_than_defaulting():
    """Silently falling back to api is exactly the bug this replaces."""
    script = ENTRYPOINT.read_text(encoding="utf-8")
    assert "exit 1" in script


def test_the_worker_target_matches_the_arq_settings_class():
    """A typo here is only discovered in production, so pin it to the real
    import path."""
    script = ENTRYPOINT.read_text(encoding="utf-8")
    target = re.search(r"arq (\S+)", script).group(1)
    module, _, attr = target.rpartition(".")
    import importlib

    assert hasattr(importlib.import_module(module), attr)
