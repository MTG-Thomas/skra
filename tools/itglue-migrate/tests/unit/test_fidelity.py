"""Unit tests for post-import attachment and image fidelity checks (issue #24)."""

from __future__ import annotations

import pytest

import itglue_migrate.cli as cli_module
from itglue_migrate.cli import (
    _check_url_reachable,
    _invert_entity_identities,
    _probe_allowed_origins,
)
from itglue_migrate.state_fetcher import ExistingState
from itglue_migrate.verification import (
    BROKEN_LINK,
    INACCESSIBLE_URL,
    MISSING_UPLOAD,
    UNEXPECTED_UPLOAD,
    UNRESOLVED_ENTITY,
    MigratedAttachment,
    extract_markdown_image_urls,
    reconcile_migrated_attachments,
    verify_migrated_document_images,
)


def test_extract_markdown_image_urls_in_document_order() -> None:
    content = (
        "# Guide\n\n"
        "![diagram](https://files.example.invalid/a.png)\n\n"
        "![logo](./images/logo.png \"Logo\")\n\n"
        "No image here: [docs](https://example.invalid/docs).\n"
    )

    assert extract_markdown_image_urls(content) == [
        "https://files.example.invalid/a.png",
        "./images/logo.png",
    ]


def test_extract_markdown_image_urls_empty_content() -> None:
    assert extract_markdown_image_urls("") == []
    assert extract_markdown_image_urls("Just text, no images.") == []


def test_reconcile_migrated_attachments_clean_match() -> None:
    expected = [("configurations", "123", "manual.pdf")]

    result = reconcile_migrated_attachments(
        expected,
        [("configurations", "123", "manual.pdf")],
    )

    assert result.ok is True
    assert result.expected_count == 1
    assert result.migrated_count == 1
    assert result.to_dict()["failure_count"] == 0


def test_reconcile_migrated_attachments_reports_missing_and_unexpected() -> None:
    result = reconcile_migrated_attachments(
        [("configurations", "123", "manual.pdf")],
        [("configurations", "123", "stray.pdf")],
    )

    assert result.ok is False
    categories = [failure.category for failure in result.failures]
    assert categories == [MISSING_UPLOAD, UNEXPECTED_UPLOAD]
    missing = result.failures[0].to_dict()
    assert missing["entity_type"] == "configurations"
    assert missing["entity_id"] == "123"
    assert missing["filename"] == "manual.pdf"


def test_reconcile_migrated_attachments_counts_duplicate_filenames() -> None:
    """Same-name files must be counted per occurrence, not collapsed."""
    result = reconcile_migrated_attachments(
        [
            ("configurations", "123", "manual.pdf"),
            ("configurations", "123", "manual.pdf"),
        ],
        [("configurations", "123", "manual.pdf")],
    )

    assert result.ok is False
    assert result.expected_count == 2
    assert result.migrated_count == 1
    assert len(result.failures) == 1
    assert result.failures[0].category == MISSING_UPLOAD
    assert result.failures[0].filename == "manual.pdf"


def test_reconcile_migrated_attachments_counts_duplicate_records() -> None:
    """Extra same-name migrated records must surface as unexpected uploads."""
    result = reconcile_migrated_attachments(
        [("configurations", "123", "manual.pdf")],
        [
            ("configurations", "123", "manual.pdf"),
            ("configurations", "123", "manual.pdf"),
        ],
    )

    assert result.ok is False
    assert result.expected_count == 1
    assert result.migrated_count == 2
    assert len(result.failures) == 1
    assert result.failures[0].category == UNEXPECTED_UPLOAD


def test_reconcile_migrated_attachments_reports_unresolved_entities() -> None:
    result = reconcile_migrated_attachments(
        [],
        [],
        [
            MigratedAttachment(
                attachment_id="att-9",
                entity_type="configuration",
                entity_id="unknown-uuid",
                filename="orphan.pdf",
            )
        ],
    )

    assert result.ok is False
    assert len(result.failures) == 1
    failure = result.failures[0]
    assert failure.category == UNRESOLVED_ENTITY
    assert failure.entity_id == "unknown-uuid"
    assert failure.filename == "orphan.pdf"


def test_verify_migrated_document_images_clean_absolute_links() -> None:
    result = verify_migrated_document_images(
        document_id="200",
        document_name="Guide",
        expected_count=2,
        image_urls=[
            "https://files.example.invalid/a.png",
            "https://files.example.invalid/b.png",
        ],
    )

    assert result.ok is True
    assert result.expected_count == 2
    assert result.present_count == 2


def test_verify_migrated_document_images_flags_relative_link() -> None:
    result = verify_migrated_document_images(
        document_id="200",
        document_name="Guide",
        expected_count=1,
        image_urls=["1/docs/200/images/img123"],
    )

    assert result.ok is False
    assert result.present_count == 0
    assert result.failures[0].category == BROKEN_LINK
    assert result.failures[0].document_id == "200"
    assert any(
        failure.category == MISSING_UPLOAD for failure in result.failures
    )


def test_verify_migrated_document_images_flags_upload_deficit() -> None:
    result = verify_migrated_document_images(
        document_id="200",
        document_name="Guide",
        expected_count=3,
        image_urls=["https://files.example.invalid/a.png"],
    )

    assert result.ok is False
    assert result.present_count == 1
    deficit = [
        failure for failure in result.failures if failure.category == MISSING_UPLOAD
    ]
    assert len(deficit) == 1
    assert "3" in deficit[0].message and "1" in deficit[0].message


def test_invert_entity_identities_resolves_uuids_to_export_vocabulary() -> None:
    state = ExistingState()
    state.config_by_itglue_id = {"123": "uuid-config-1"}
    state.document_by_itglue_id = {"200": "uuid-doc-1"}
    state.custom_asset_by_itglue_id = {"6001": "uuid-asset-1"}

    inverted = _invert_entity_identities(state)

    assert inverted["uuid-config-1"] == ("configurations", "123")
    assert inverted["uuid-doc-1"] == ("documents", "200")
    assert inverted["uuid-asset-1"] == ("custom_assets", "6001")
    assert "unknown-uuid" not in inverted


def test_check_url_reachable_returns_false_without_network() -> None:
    assert _check_url_reachable("http://127.0.0.1:1/unreachable.png") is False


def test_url_probe_policy_blocks_non_public_destinations() -> None:
    """Crafted content must not turn opt-in probes toward internal targets."""
    assert _check_url_reachable("http://127.0.0.1:1/unreachable.png") is False
    assert _check_url_reachable("http://localhost/unreachable.png") is False
    assert _check_url_reachable("http://169.254.169.254/latest/") is False
    assert _check_url_reachable("http://[::1]/unreachable.png") is False
    assert _check_url_reachable("ftp://files.example.invalid/a.png") is False
    assert _check_url_reachable("not a url") is False


def test_probe_allowed_origins_uses_effective_ports() -> None:
    """The allowlist holds exact origins with default ports resolved."""
    allowed = _probe_allowed_origins(
        "https://api.example.com/v1",
        "http://cdn.example.com, https://s3.example.com:8443",
    )

    assert allowed == frozenset(
        {
            ("https", "api.example.com", 443),
            ("http", "cdn.example.com", 80),
            ("https", "s3.example.com", 8443),
        }
    )


def test_probe_allowed_origins_rejects_invalid_entries() -> None:
    """Bare hosts, wrong schemes, and bad ports fail fast with clear errors."""
    with pytest.raises(ValueError, match="scheme"):
        _probe_allowed_origins("https://api.example.com", "cdn.example.com")
    with pytest.raises(ValueError, match="scheme"):
        _probe_allowed_origins(
            "https://api.example.com", "ftp://files.example.invalid/a.png"
        )
    with pytest.raises(ValueError, match="port"):
        _probe_allowed_origins("https://api.example.com", "https://bad.example.com:abc")


def test_check_url_reachable_only_probes_allowlisted_hosts() -> None:
    """Unlisted hosts are refused; listed ones still fail closed offline."""
    assert (
        _check_url_reachable(
            "http://127.0.0.1:1/unreachable.png",
            allowed_origins=frozenset({("http", "127.0.0.1", 1)}),
        )
        is False
    )
    assert (
        _check_url_reachable(
            "http://127.0.0.1:1/unreachable.png",
            allowed_origins=frozenset({("http", "other.example.invalid", 80)}),
        )
        is False
    )


def test_check_url_reachable_enforces_effective_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same host with a different port is a different origin: never requested."""
    calls: list[str] = []

    def fake_head(url: str, **kwargs: object) -> _FakeHeadResponse:
        calls.append(url)
        return _FakeHeadResponse(200, {})

    monkeypatch.setattr(cli_module.httpx, "head", fake_head)
    allowed = frozenset({("http", "127.0.0.1", 8000)})

    assert (
        _check_url_reachable("http://127.0.0.1:3903/x", allowed_origins=allowed)
        is False
    )
    assert calls == []
    assert (
        _check_url_reachable("http://127.0.0.1:8000/x", allowed_origins=allowed)
        is True
    )
    assert calls == ["http://127.0.0.1:8000/x"]


def test_check_url_reachable_refuses_cross_port_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redirects to the same host on another port are refused unrequested."""
    calls: list[str] = []

    def fake_head(url: str, **kwargs: object) -> _FakeHeadResponse:
        calls.append(url)
        return _FakeHeadResponse(302, {"location": "http://127.0.0.1:3903/x"})

    monkeypatch.setattr(cli_module.httpx, "head", fake_head)
    allowed = frozenset({("http", "127.0.0.1", 8000)})

    assert (
        _check_url_reachable("http://127.0.0.1:8000/a.png", allowed_origins=allowed)
        is False
    )
    assert calls == ["http://127.0.0.1:8000/a.png"]


class _FakeHeadResponse:
    def __init__(self, status_code: int, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.headers = headers or {}


def test_check_url_reachable_refuses_redirect_to_unlisted_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redirect targets are re-validated; the evil hop is never requested."""
    calls: list[str] = []

    def fake_head(url: str, **kwargs: object) -> _FakeHeadResponse:
        calls.append(url)
        return _FakeHeadResponse(302, {"location": "http://169.254.169.254/x"})

    monkeypatch.setattr(cli_module.httpx, "head", fake_head)

    assert (
        _check_url_reachable(
            "https://cdn.example.invalid/a.png",
            allowed_origins=frozenset({("https", "cdn.example.invalid", 443)}),
        )
        is False
    )
    assert calls == ["https://cdn.example.invalid/a.png"]


def test_check_url_reachable_follows_redirect_to_allowlisted_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Allowlisted redirect chains resolve normally."""
    calls: list[str] = []

    def fake_head(url: str, **kwargs: object) -> _FakeHeadResponse:
        calls.append(url)
        if url == "https://cdn.example.invalid/a.png":
            return _FakeHeadResponse(302, {"location": "/b.png"})
        return _FakeHeadResponse(200, {})

    monkeypatch.setattr(cli_module.httpx, "head", fake_head)

    assert (
        _check_url_reachable(
            "https://cdn.example.invalid/a.png",
            allowed_origins=frozenset({("https", "cdn.example.invalid", 443)}),
        )
        is True
    )
    assert calls == [
        "https://cdn.example.invalid/a.png",
        "https://cdn.example.invalid/b.png",
    ]


def test_verify_migrated_document_images_records_unreachable_url() -> None:
    result = verify_migrated_document_images(
        document_id="200",
        document_name="Guide",
        expected_count=1,
        image_urls=["https://files.example.invalid/a.png"],
        url_checker=lambda _url: False,
    )

    assert result.ok is False
    assert result.present_count == 0
    assert result.failures[0].category == INACCESSIBLE_URL
    assert result.failures[0].url == "https://files.example.invalid/a.png"
