import pytest
from pydantic import ValidationError

from app.schemas.tenant import SlaBand, SlaPolicy, TenantCreate, WazuhConnectionIn


def test_slug_is_normalised_to_lowercase():
    assert TenantCreate(slug="  ACME-Corp  ", name="Acme").slug == "acme-corp"


@pytest.mark.parametrize(
    "slug",
    [
        "ab",              # too short
        "-acme",           # leading hyphen
        "acme-",           # trailing hyphen
        "acme corp",       # space
        "acme/../etc",     # path traversal into the ingest URL
        "acme%2f",         # percent-encoding
        "a" * 41,          # too long
    ],
)
def test_a_slug_that_would_break_the_ingest_url_is_refused(slug):
    with pytest.raises(ValidationError):
        TenantCreate(slug=slug, name="Acme")


def test_cidrs_are_normalised_and_host_bits_tolerated():
    tenant = TenantCreate(
        slug="acme-corp", name="Acme", ingest_cidrs=["41.1.2.3/24", "2001:db8::/32"]
    )
    assert tenant.ingest_cidrs == ["41.1.2.0/24", "2001:db8::/32"]


def test_a_bad_cidr_is_refused():
    with pytest.raises(ValidationError):
        TenantCreate(slug="acme-corp", name="Acme", ingest_cidrs=["not-an-address"])


def test_alert_floor_is_bounded_to_the_wazuh_ramp():
    with pytest.raises(ValidationError):
        TenantCreate(slug="acme-corp", name="Acme", alert_floor=16)


def test_manager_url_must_be_https():
    with pytest.raises(ValidationError):
        WazuhConnectionIn(base_url="http://wazuh.acme.co.za", username="u", password="p")


def test_manager_url_loses_its_trailing_slash():
    connection = WazuhConnectionIn(
        base_url="https://wazuh.acme.co.za/", username="u", password="p"
    )
    assert connection.base_url == "https://wazuh.acme.co.za"


def test_sla_bands_are_sorted_by_severity():
    policy = SlaPolicy(
        bands=[
            SlaBand(severity_min=12, respond_minutes=15, resolve_minutes=120),
            SlaBand(severity_min=7, respond_minutes=60, resolve_minutes=480),
        ]
    )
    assert [band.severity_min for band in policy.bands] == [7, 12]


def test_a_duplicated_severity_floor_is_refused():
    with pytest.raises(ValidationError):
        SlaPolicy(
            bands=[
                SlaBand(severity_min=7, respond_minutes=60, resolve_minutes=120),
                SlaBand(severity_min=7, respond_minutes=30, resolve_minutes=120),
            ]
        )


def test_a_higher_severity_may_not_be_given_more_time():
    """Almost always a typo, and an expensive one: it silently relaxes the SLA on
    exactly the incidents that matter most."""
    with pytest.raises(ValidationError) as exc:
        SlaPolicy(
            bands=[
                SlaBand(severity_min=7, respond_minutes=15, resolve_minutes=120),
                SlaBand(severity_min=13, respond_minutes=60, resolve_minutes=120),
            ]
        )
    assert "higher severity must be tighter" in str(exc.value)


def test_resolution_may_not_be_tighter_than_response():
    with pytest.raises(ValidationError):
        SlaBand(severity_min=7, respond_minutes=120, resolve_minutes=60)


def test_an_empty_policy_is_valid_and_means_no_sla():
    assert SlaPolicy().bands == []
