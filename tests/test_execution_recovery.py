"""Real regressions found during the ordered ten-station LIVE window."""

from backlink_submitter.batch import official_url
from backlink_submitter.contracts import safe_artifact


def test_normal_login_return_query_and_observed_app_subdomain_are_allowed():
    assert official_url("https://sideprojects.net/login?next=/projects/submit", "sideprojects.net")
    assert official_url("https://app.beehiiv.com/signup", "beehiiv.com")
    assert official_url("https://www.promoteproject.com/#", "promoteproject.com")
    assert not official_url("https://evilbeehiiv.com/signup", "beehiiv.com")
    assert not official_url("https://sideprojects.net/callback?token=secret", "sideprojects.net")


def test_reason_histogram_can_persist_owner_blocker_without_secret_keys():
    safe_artifact({"window_reasons": [{"reason": "OWNER_PASSWORD_REQUIRED", "count": 1}]})
