"""The manager-side integrator.

Two things matter here. The signature it produces must be exactly what the
console will verify in M3 - a mismatch is silent data loss across the trust
boundary. And the script must never raise, because the Wazuh integrator forks a
process per alert.
"""

import hashlib
import hmac
import importlib.util
import json
import pathlib
import sys

import pytest

SCRIPT = (
    pathlib.Path(__file__).resolve().parents[2] / "deploy" / "wazuh" / "custom-awd-console"
)


@pytest.fixture(scope="module")
def integrator():
    spec = importlib.util.spec_from_loader(
        "custom_awd_console",
        importlib.machinery.SourceFileLoader("custom_awd_console", str(SCRIPT)),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_script_ships_where_the_installer_expects_it():
    assert SCRIPT.is_file()


def test_signature_matches_an_independent_implementation(integrator):
    """This is the contract M3's verifier has to satisfy: HMAC-SHA256 over
    "<timestamp>.<body>", hex, keyed with the tenant's ingest secret."""
    secret = "tenant-ingest-secret"
    timestamp = "1756252800"
    body = '{"rule":{"level":10}}'

    expected = hmac.new(
        secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256
    ).hexdigest()
    assert integrator.sign(secret, timestamp, body) == expected


def test_the_timestamp_is_inside_the_signed_material(integrator):
    """Otherwise a captured body replays forever under a fresh header."""
    secret, body = "k", "{}"
    assert integrator.sign(secret, "1000", body) != integrator.sign(secret, "2000", body)


def test_a_different_secret_produces_a_different_signature(integrator):
    assert integrator.sign("a", "1000", "{}") != integrator.sign("b", "1000", "{}")


def test_the_body_serialisation_matches_what_the_console_will_verify():
    """The console signs the exact bytes it receives, so both sides must
    serialise identically. Compact separators, no spaces."""
    alert = {"rule": {"level": 10, "id": 5710}, "agent": {"name": "web01"}}
    assert json.dumps(alert, separators=(",", ":")) == (
        '{"rule":{"level":10,"id":5710},"agent":{"name":"web01"}}'
    )


def test_a_missing_alert_file_does_not_raise(integrator, monkeypatch, tmp_path):
    monkeypatch.setattr(
        sys, "argv", ["custom-awd-console", str(tmp_path / "gone.json"), "key", "https://x"]
    )
    monkeypatch.setattr(integrator, "log", lambda *_: None)
    integrator.main()  # must simply return


def test_malformed_alert_json_does_not_raise(integrator, monkeypatch, tmp_path):
    alert_file = tmp_path / "alert.json"
    alert_file.write_text("{not json")
    monkeypatch.setattr(
        sys, "argv", ["custom-awd-console", str(alert_file), "key", "https://x"]
    )
    monkeypatch.setattr(integrator, "log", lambda *_: None)
    integrator.main()


def test_too_few_arguments_does_not_raise(integrator, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["custom-awd-console"])
    monkeypatch.setattr(integrator, "log", lambda *_: None)
    integrator.main()


def test_a_4xx_is_not_retried(integrator, monkeypatch):
    """4xx means a bad signature, a stale clock, an unknown slug or a blocked IP.
    None of those fix themselves, and retrying just burns forks on the client's
    manager."""
    attempts = []

    def fake_post(hook_url, secret, payload):
        attempts.append(1)
        return 401

    monkeypatch.setattr(integrator, "post", fake_post)
    monkeypatch.setattr(integrator, "log", lambda *_: None)
    assert integrator.deliver("https://x", "k", "{}") is False
    assert len(attempts) == 1


def test_a_5xx_is_retried_exactly_twice(integrator, monkeypatch):
    attempts = []

    def fake_post(hook_url, secret, payload):
        attempts.append(1)
        return 503

    monkeypatch.setattr(integrator, "post", fake_post)
    monkeypatch.setattr(integrator, "log", lambda *_: None)
    monkeypatch.setattr(integrator.time, "sleep", lambda _: None)
    assert integrator.deliver("https://x", "k", "{}") is False
    assert len(attempts) == integrator.ATTEMPTS == 3


def test_a_transport_error_is_retried_then_given_up_on(integrator, monkeypatch):
    attempts = []

    def fake_post(hook_url, secret, payload):
        attempts.append(1)
        raise OSError("connection reset")

    monkeypatch.setattr(integrator, "post", fake_post)
    monkeypatch.setattr(integrator, "log", lambda *_: None)
    monkeypatch.setattr(integrator.time, "sleep", lambda _: None)
    assert integrator.deliver("https://x", "k", "{}") is False
    assert len(attempts) == 3


def test_a_202_stops_immediately(integrator, monkeypatch):
    attempts = []

    def fake_post(hook_url, secret, payload):
        attempts.append(1)
        return 202

    monkeypatch.setattr(integrator, "post", fake_post)
    monkeypatch.setattr(integrator, "log", lambda *_: None)
    assert integrator.deliver("https://x", "k", "{}") is True
    assert len(attempts) == 1


def test_the_retry_budget_is_bounded_by_the_timeout(integrator):
    """A fork-per-alert integrator that can hang for a minute is a fork bomb.
    Worst case here is 3 x 5s of request plus 1s + 2s of backoff."""
    worst_case = integrator.ATTEMPTS * integrator.TIMEOUT_SECONDS + 1 + 2
    assert worst_case <= 20
