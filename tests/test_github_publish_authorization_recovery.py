from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_publish_modal_distinguishes_personal_and_organization_permission_errors() -> None:
    source = (ROOT / "web/github-organization-publish.js").read_text(encoding="utf-8")

    assert "target?.kind === 'organization'" in source
    assert "personal account ${publishOwnerInput.value}" in source
    assert "An organization owner may also need to approve Amosclaud" in source
    assert "GitHub did not authorize repository creation for this owner" not in source


def test_failed_publish_can_reconnect_without_losing_the_user_form() -> None:
    source = (ROOT / "web/github-organization-publish.js").read_text(encoding="utf-8")

    assert "Reconnect GitHub and continue" in source
    assert "amosclaud-pending-github-publish" in source
    assert "sessionStorage.setItem(PENDING_PUBLISH_KEY" in source
    assert "sessionStorage.getItem(PENDING_PUBLISH_KEY" in source
    assert "restorePendingPublish()" in source
    assert "GitHub reconnected. Your publish details were restored." in source


def test_permission_failure_stays_in_modal_and_offers_direct_reauthorization() -> None:
    source = (ROOT / "web/github-organization-publish.js").read_text(encoding="utf-8")

    assert "error.status === 401 || error.status === 403" in source
    assert "showReconnectAction(message)" in source
    assert "window.location.assign(targetResult.reconnect_url" in source
    assert "/api/v1/github/connect-organizations" in source
