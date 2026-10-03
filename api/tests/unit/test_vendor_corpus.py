"""Unit tests for the vendor corpus import service (issue #55)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.services.vendor_corpus import (
    INLINE_BYTE_BUDGET,
    AccessClass,
    AssetKind,
    ConversionRecord,
    CorpusAsset,
    CorpusManifest,
    FetchStatus,
    assert_import_target_allowed,
    build_dry_run_report,
    dokuwiki_to_markdown,
    is_large_binary,
    outline_seed_to_articles,
    reference_uri,
    validate_manifest,
)

SHA = "a" * 64


def _asset(**overrides) -> CorpusAsset:
    base = {
        "local_path": "pages/example.txt",
        "source_url": "https://example.test/docs/example",
        "kind": AssetKind.PAGE,
        "status": FetchStatus.OK,
        "bytes": 120,
        "sha256": SHA,
    }
    base.update(overrides)
    return CorpusAsset(**base)


def _manifest(**overrides) -> CorpusManifest:
    base = {
        "corpus": "example-corpus",
        "vendor": "Example Vendor",
        "access_class": AccessClass.PUBLIC_ONLY,
        "captured_at": datetime(2026, 4, 30, tzinfo=UTC),
        "source_root_url": "https://example.test/docs",
        "assets": [
            _asset(),
            _asset(
                local_path="media/logo.png",
                source_url="https://example.test/docs/logo.png",
                kind=AssetKind.MEDIA,
                bytes=500,
            ),
            _asset(
                local_path="media/blocked.pdf",
                source_url="https://example.test/docs/blocked.pdf",
                kind=AssetKind.MEDIA,
                status=FetchStatus.FORBIDDEN,
                http_status=403,
                bytes=None,
                sha256=None,
            ),
            _asset(
                local_path="media/missing.pdf",
                source_url="https://example.test/docs/missing.pdf",
                kind=AssetKind.MEDIA,
                status=FetchStatus.NOT_FOUND,
                http_status=404,
                bytes=None,
                sha256=None,
            ),
        ],
    }
    base.update(overrides)
    return CorpusManifest(**base)


# --- Manifest validation ----------------------------------------------------


def test_validate_manifest_accepts_well_formed_dict() -> None:
    manifest = validate_manifest(_manifest().model_dump(mode="json"))
    assert manifest.corpus == "example-corpus"
    assert len(manifest.assets) == 4


def test_archived_asset_requires_bytes_and_sha256() -> None:
    with pytest.raises(ValidationError):
        _asset(bytes=None, sha256=None)


def test_missing_asset_must_not_record_bytes_or_sha256() -> None:
    with pytest.raises(ValidationError):
        _asset(status=FetchStatus.FORBIDDEN, http_status=403)
    with pytest.raises(ValidationError):
        _asset(status=FetchStatus.SKIPPED, bytes=None, sha256=SHA)


def test_sha256_must_be_64_lowercase_hex() -> None:
    with pytest.raises(ValidationError):
        _asset(sha256="ZZZ")


def test_manifest_rejects_unknown_version() -> None:
    with pytest.raises(ValidationError):
        _manifest(manifest_version="99")


def test_manifest_rejects_duplicate_local_paths() -> None:
    with pytest.raises(ValidationError):
        _manifest(assets=[_asset(), _asset()])


def test_summary_and_missing_counts() -> None:
    manifest = _manifest()
    summary = manifest.summary()
    assert summary["total"] == 4
    assert summary["ok"] == 2
    assert summary["forbidden"] == 1
    assert summary["not-found"] == 1
    assert [a.local_path for a in manifest.missing()] == [
        "media/blocked.pdf",
        "media/missing.pdf",
    ]


# --- Large binary policy ----------------------------------------------------


def test_binary_kind_is_always_large() -> None:
    asset = _asset(kind=AssetKind.BINARY, bytes=10)
    assert is_large_binary(asset)


def test_page_over_budget_is_large() -> None:
    asset = _asset(bytes=INLINE_BYTE_BUDGET + 1)
    assert is_large_binary(asset)


def test_small_page_is_not_large() -> None:
    assert not is_large_binary(_asset())


def test_missing_asset_is_never_large() -> None:
    asset = _asset(status=FetchStatus.ERROR, bytes=None, sha256=None)
    assert not is_large_binary(asset)


def test_reference_uri_joins_base_and_path() -> None:
    asset = _asset(local_path="bin/driver.zip")
    assert (
        reference_uri(asset, "s3://vendor-corpus/example-corpus/")
        == "s3://vendor-corpus/example-corpus/bin/driver.zip"
    )


# --- Target guard -----------------------------------------------------------


def test_unknown_target_rejected() -> None:
    with pytest.raises(ValueError, match="unknown import target"):
        assert_import_target_allowed(_manifest(), "public-docs")


def test_authorized_corpus_rejected_for_public_target() -> None:
    manifest = _manifest(access_class=AccessClass.AUTHORIZED)
    with pytest.raises(ValueError, match="cannot receive authorized corpora"):
        assert_import_target_allowed(manifest, "outline-staging-public")


def test_public_corpus_allowed_for_public_target() -> None:
    assert_import_target_allowed(_manifest(), "outline-staging-public")


@pytest.mark.parametrize("target", ["outline-staging-authorized", "itglue-curated"])
def test_authorized_corpus_allowed_for_restricted_targets(target: str) -> None:
    manifest = _manifest(access_class=AccessClass.AUTHORIZED)
    assert_import_target_allowed(manifest, target)


# --- DokuWiki conversion ----------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("====== Title ======", "# Title"),
        ("===== Section =====", "## Section"),
        ("==== Deep ====", "### Deep"),
        ("**bold** and //italic// and ''code''", "**bold** and *italic* and `code`"),
        ("[[page:id|Nice title]]", "[Nice title](page:id)"),
        ("[[page:id]]", "[page:id](page:id)"),
        (
            "[[https://example.test/x|External]]",
            "[External](https://example.test/x)",
        ),
        ("{{media:logo.png?200|Logo}}", "![Logo](media:logo.png)"),
        ("  * item one", "* item one"),
        ("  * item one\n    * nested", "* item one\n  * nested"),
        ("  - first", "1. first"),
        ("----", "---"),
        ("<code>\nls -la\n</code>", "```\nls -la\n```"),
    ],
)
def test_dokuwiki_inline_conversions(source: str, expected: str) -> None:
    assert dokuwiki_to_markdown(source) == expected + "\n"


def test_dokuwiki_table_with_header_separator() -> None:
    source = "^ Name ^ Version ^\n| Widget | 2.0 |"
    assert dokuwiki_to_markdown(source) == ("| Name | Version |\n| --- | --- |\n| Widget | 2.0 |\n")


def test_dokuwiki_multiline_document() -> None:
    source = "====== Guide ======\n\nSee [[install|setup]] for **details**.\n"
    assert dokuwiki_to_markdown(source) == ("# Guide\n\nSee [setup](install) for **details**.\n")


# --- outline-seed splitting -------------------------------------------------


def test_seed_splits_h2_sections_into_articles() -> None:
    markdown = "# Vendor Tutorials\n\nIntro line.\n\n## Getting Started\n\nBody one.\n\n## Advanced Setup\n\nBody two.\n"
    articles = outline_seed_to_articles(markdown, base_path="/Vendor/Example")
    assert [a.title for a in articles] == ["Getting Started", "Advanced Setup"]
    assert articles[0].path == "/Vendor/Example/getting-started"
    assert articles[1].path == "/Vendor/Example/advanced-setup"
    assert articles[0].content == "Body one.\n"
    assert articles[0].index == 0
    assert articles[1].index == 1


def test_seed_with_no_sections_returns_empty() -> None:
    assert outline_seed_to_articles("# Just a title\n\nNo sections.\n") == []


def test_seed_empty_section_has_empty_content() -> None:
    articles = outline_seed_to_articles("## Empty\n\n## Next\n\nText\n")
    assert articles[0].content == ""
    assert articles[1].content == "Text\n"


# --- Dry-run report ---------------------------------------------------------


def _conversions() -> list[ConversionRecord]:
    return [
        ConversionRecord(
            local_path="pages/example.txt",
            article_path="/Vendor/example",
            title="Example",
            status="converted",
        ),
        ConversionRecord(
            local_path="media/logo.png", status="skipped", detail="binary passthrough"
        ),
    ]


def test_dry_run_report_ready_when_all_archived_assets_converted() -> None:
    report = build_dry_run_report(
        _manifest(), _conversions(), "outline-staging-public", "s3://vendor-corpus/example"
    )
    assert report["corpus"] == "example-corpus"
    assert report["assets"]["total"] == 4
    assert report["converted"] == 1
    assert report["conversion_errors"] == 0
    assert report["ready_for_import"] is True
    assert any("forbidden" in w and "403" in w for w in report["warnings"])
    assert any("not-found" in w and "404" in w for w in report["warnings"])


def test_dry_run_report_not_ready_with_unconverted_or_failed_assets() -> None:
    manifest = _manifest()
    report = build_dry_run_report(
        manifest,
        [ConversionRecord(local_path="pages/example.txt", status="error", detail="bad table")],
        "outline-staging-public",
        "s3://vendor-corpus/example",
    )
    assert report["ready_for_import"] is False
    assert report["conversion_errors"] == 1
    assert any("media/logo.png: archived but not converted" in w for w in report["warnings"])


def test_dry_run_report_lists_large_binaries_with_reference_uris() -> None:
    manifest = _manifest(
        assets=[
            _asset(
                local_path="bin/driver.zip",
                source_url="https://example.test/docs/driver.zip",
                kind=AssetKind.BINARY,
                bytes=50_000_000,
            )
        ]
    )
    report = build_dry_run_report(
        manifest,
        [ConversionRecord(local_path="bin/driver.zip", status="skipped")],
        "outline-staging-public",
        "s3://vendor-corpus/example",
    )
    assert report["large_binaries"] == [
        {
            "local_path": "bin/driver.zip",
            "bytes": 50_000_000,
            "reference_uri": "s3://vendor-corpus/example/bin/driver.zip",
        }
    ]
    assert any("stays in durable storage" in w for w in report["warnings"])


def test_dry_run_report_rejects_disallowed_target() -> None:
    manifest = _manifest(access_class=AccessClass.AUTHORIZED)
    with pytest.raises(ValueError, match="cannot receive authorized corpora"):
        build_dry_run_report(manifest, [], "outline-staging-public", "s3://vendor-corpus/example")


def test_dry_run_report_warns_on_authorized_corpus() -> None:
    manifest = _manifest(access_class=AccessClass.AUTHORIZED)
    report = build_dry_run_report(
        manifest, _conversions(), "outline-staging-authorized", "s3://vendor-corpus/example"
    )
    assert any("must not be publicly shared" in w for w in report["warnings"])
