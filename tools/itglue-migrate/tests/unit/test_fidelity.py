"""Unit tests for post-import attachment and image fidelity checks (issue #24)."""

from __future__ import annotations

from itglue_migrate.cli import _check_url_reachable, _invert_entity_identities
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
