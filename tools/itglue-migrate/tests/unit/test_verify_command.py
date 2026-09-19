"""Command-level tests for fidelity verification (issue #24).

Uses a fake read-only API client so `_run_verify` orchestration, report
aggregation, and exit codes are covered without network access.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import itglue_migrate.cli as cli_module
from itglue_migrate.cli import _run_verify, app

FIXTURE_EXPORT = Path(__file__).parents[4] / "tests" / "fixtures" / "minimal-export"

ORGS = [
    {"id": "org-uuid-acme", "name": "Acme Corp Test", "metadata": {"itglue_id": "1001"}},
    {
        "id": "org-uuid-test",
        "name": "Test Technologies Inc",
        "metadata": {"itglue_id": "1002"},
    },
]


def make_fake_client(
    *,
    documents: list[dict[str, Any]] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    document_content: str = "",
    orgs: list[dict[str, Any]] | None = None,
    fail_list_attachments: bool = False,
    fail_get_document: bool = False,
    download_urls: dict[str, str] | None = None,
    forbid_download_url: bool = True,
) -> type:
    """Build a fake read-only BifrostDocsClient class with canned data."""
    from itglue_migrate.api_client import APIError

    doc_list = documents if documents is not None else []
    attachment_list = attachments if attachments is not None else []
    org_list = orgs if orgs is not None else ORGS
    url_map = download_urls if download_urls is not None else {}

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def list_organizations(self) -> list[dict[str, Any]]:
            return org_list

        async def list_configuration_types(self, **kwargs: Any) -> list[Any]:
            return []

        async def list_configuration_statuses(self, **kwargs: Any) -> list[Any]:
            return []

        async def list_custom_asset_types(self, **kwargs: Any) -> list[Any]:
            return []

        async def _page(
            self, items: list[dict[str, Any]], limit: int, offset: int
        ) -> dict[str, Any]:
            return {"items": items[offset : offset + limit], "total": len(items)}

        async def list_configurations(self, org_id: str, **kwargs: Any) -> dict[str, Any]:
            return await self._page([], kwargs.get("limit", 100), kwargs.get("offset", 0))

        async def list_locations(self, org_id: str, **kwargs: Any) -> dict[str, Any]:
            return await self._page([], kwargs.get("limit", 100), kwargs.get("offset", 0))

        async def list_documents(self, org_id: str, **kwargs: Any) -> dict[str, Any]:
            docs = [d for d in doc_list if d.get("_org") in (None, org_id)]
            return await self._page(docs, kwargs.get("limit", 100), kwargs.get("offset", 0))

        async def list_passwords(self, org_id: str, **kwargs: Any) -> dict[str, Any]:
            return await self._page([], kwargs.get("limit", 100), kwargs.get("offset", 0))

        async def list_custom_assets(self, org_id: str, **kwargs: Any) -> dict[str, Any]:
            return await self._page([], kwargs.get("limit", 100), kwargs.get("offset", 0))

        async def list_relationships(self, *args: Any, **kwargs: Any) -> list[Any]:
            return []

        async def list_attachments(self, org_id: str, **kwargs: Any) -> dict[str, Any]:
            if fail_list_attachments:
                raise APIError(status_code=500, message="attachment list boom")
            recs = [r for r in attachment_list if r.get("_org") in (None, org_id)]
            return await self._page(recs, kwargs.get("limit", 100), kwargs.get("offset", 0))

        async def get_attachment_download_url(
            self, org_id: str, attachment_id: str
        ) -> dict[str, Any]:
            if forbid_download_url:
                raise AssertionError("download URL must not be fetched without --check-urls")
            return {"download_url": url_map[str(attachment_id)], "filename": "f"}

        async def get_document(self, org_id: str, doc_id: str) -> dict[str, Any]:
            if fail_get_document:
                raise APIError(status_code=500, message="document fetch boom")
            return {"id": doc_id, "content": document_content}

    return FakeClient


def _copy_fixture(tmp_path: Path) -> Path:
    export = tmp_path / "export"
    shutil.copytree(FIXTURE_EXPORT, export)
    return export


@pytest.mark.asyncio
async def test_run_verify_reports_missing_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An export file with no migrated record fails with detail and exit 1."""
    export = _copy_fixture(tmp_path)
    attach_dir = export / "attachments" / "configurations" / "2001"
    attach_dir.mkdir(parents=True)
    (attach_dir / "manual.pdf").write_bytes(b"PDF")

    monkeypatch.setattr(
        cli_module,
        "BifrostDocsClient",
        make_fake_client(
            documents=[
                {
                    "id": "uuid-doc-1",
                    "name": "Test Onboarding Guide",
                    "metadata": {"itglue_id": "3001"},
                    "_org": "org-uuid-acme",
                }
            ],
            document_content="# Guide\n\n![a](https://files.example.invalid/a.png)\n",
        ),
    )

    output = tmp_path / "fidelity.json"
    exit_code = await _run_verify(
        export_path=export,
        api_url="http://api.example.invalid",
        token="token",
        target_org=None,
        check_urls=False,
        output=output,
    )

    assert exit_code == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema_version"] == 1
    assert report["summary"]["failure_categories"] == {"missing_upload": 1}
    assert report["summary"]["follow_up_required"] is True
    acme = next(o for o in report["organizations"] if o["name"] == "Acme Corp Test")
    assert acme["attachments"]["expected_count"] == 1
    assert acme["attachments"]["failure_count"] == 1
    failure = acme["attachments"]["failures"][0]
    assert failure["category"] == "missing_upload"
    assert failure["entity_id"] == "2001"
    assert failure["filename"] == "manual.pdf"
    assert acme["embedded_images"]["present_count"] == 1
    assert acme["embedded_images"]["failure_count"] == 0


@pytest.mark.asyncio
async def test_run_verify_clean_export_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fully migrated export with no gaps verifies clean with exit 0."""
    export = _copy_fixture(tmp_path)
    monkeypatch.setattr(
        cli_module,
        "BifrostDocsClient",
        make_fake_client(
            documents=[
                {
                    "id": "uuid-doc-1",
                    "name": "Test Onboarding Guide",
                    "metadata": {"itglue_id": "3001"},
                    "_org": "org-uuid-acme",
                }
            ],
            document_content="# Guide with no images.\n",
        ),
    )

    exit_code = await _run_verify(
        export_path=export,
        api_url="http://api.example.invalid",
        token="token",
        target_org="Acme Corp Test",
        check_urls=False,
        output=None,
    )

    assert exit_code == 0


@pytest.mark.asyncio
async def test_run_verify_unknown_org_exits_one(tmp_path: Path) -> None:
    """An organization missing from the export is a usage error."""
    export = _copy_fixture(tmp_path)

    exit_code = await _run_verify(
        export_path=export,
        api_url="http://api.example.invalid",
        token="token",
        target_org="No Such Org",
        check_urls=False,
        output=None,
    )

    assert exit_code == 1


@pytest.mark.asyncio
async def test_run_verify_missing_org_is_structured_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One exported org absent from the API must fail loudly, not exit 0."""
    export = _copy_fixture(tmp_path)
    monkeypatch.setattr(cli_module, "BifrostDocsClient", make_fake_client(orgs=[]))

    output = tmp_path / "fidelity.json"
    exit_code = await _run_verify(
        export_path=export,
        api_url="http://api.example.invalid",
        token="token",
        target_org="Acme Corp Test",
        check_urls=False,
        output=output,
    )

    assert exit_code == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert len(report["organizations"]) == 1
    org = report["organizations"][0]
    assert org["bifrost_id"] is None
    assert org["attachments"]["failure_count"] == 1
    failure = org["attachments"]["failures"][0]
    assert failure["category"] == "missing_organization"
    assert "Acme Corp Test" in failure["message"]
    assert report["summary"]["follow_up_required"] is True


@pytest.mark.asyncio
async def test_run_verify_attachment_list_error_is_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An API list error must not be a warning that produces a clean result."""
    export = _copy_fixture(tmp_path)
    monkeypatch.setattr(
        cli_module, "BifrostDocsClient", make_fake_client(fail_list_attachments=True)
    )

    exit_code = await _run_verify(
        export_path=export,
        api_url="http://api.example.invalid",
        token="token",
        target_org="Acme Corp Test",
        check_urls=False,
        output=None,
    )

    assert exit_code == 1


@pytest.mark.asyncio
async def test_run_verify_document_fetch_error_is_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A document fetch error must fail with document detail, not a warning."""
    export = _copy_fixture(tmp_path)
    monkeypatch.setattr(
        cli_module,
        "BifrostDocsClient",
        make_fake_client(
            documents=[
                {
                    "id": "uuid-doc-1",
                    "name": "Test Onboarding Guide",
                    "metadata": {"itglue_id": "3001"},
                    "_org": "org-uuid-acme",
                }
            ],
            fail_get_document=True,
        ),
    )

    output = tmp_path / "fidelity.json"
    exit_code = await _run_verify(
        export_path=export,
        api_url="http://api.example.invalid",
        token="token",
        target_org="Acme Corp Test",
        check_urls=False,
        output=output,
    )

    assert exit_code == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    org = report["organizations"][0]
    failures = org["embedded_images"]["failures"]
    assert len(failures) == 1
    assert failures[0]["category"] == "api_error"
    assert failures[0]["document_id"] == "3001"


@pytest.mark.asyncio
async def test_run_verify_inaccessible_attachment_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With --check-urls, an unreachable download URL fails the attachment."""
    export = _copy_fixture(tmp_path)
    attach_dir = export / "attachments" / "documents" / "3001"
    attach_dir.mkdir(parents=True)
    (attach_dir / "stray.pdf").write_bytes(b"PDF")
    monkeypatch.setattr(
        cli_module,
        "BifrostDocsClient",
        make_fake_client(
            documents=[
                {
                    "id": "uuid-doc-1",
                    "name": "Test Onboarding Guide",
                    "metadata": {"itglue_id": "3001"},
                    "_org": "org-uuid-acme",
                }
            ],
            attachments=[
                {
                    "id": "att-1",
                    "entity_type": "document",
                    "entity_id": "uuid-doc-1",
                    "filename": "stray.pdf",
                    "_org": "org-uuid-acme",
                }
            ],
            download_urls={"att-1": "https://files.example.invalid/stray.pdf"},
            forbid_download_url=False,
        ),
    )
    monkeypatch.setattr(cli_module, "_check_url_reachable", lambda *a, **k: False)

    output = tmp_path / "fidelity.json"
    exit_code = await _run_verify(
        export_path=export,
        api_url="http://api.example.invalid",
        token="token",
        target_org="Acme Corp Test",
        check_urls=True,
        output=output,
    )

    assert exit_code == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    org = report["organizations"][0]
    failures = org["attachments"]["failures"]
    assert len(failures) == 1
    assert failures[0]["category"] == "inaccessible_url"
    assert failures[0]["filename"] == "stray.pdf"


@pytest.mark.asyncio
async def test_run_verify_accessible_attachment_url_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reachable download URL keeps a matched attachment clean."""
    export = _copy_fixture(tmp_path)
    attach_dir = export / "attachments" / "documents" / "3001"
    attach_dir.mkdir(parents=True)
    (attach_dir / "stray.pdf").write_bytes(b"PDF")
    monkeypatch.setattr(
        cli_module,
        "BifrostDocsClient",
        make_fake_client(
            documents=[
                {
                    "id": "uuid-doc-1",
                    "name": "Test Onboarding Guide",
                    "metadata": {"itglue_id": "3001"},
                    "_org": "org-uuid-acme",
                }
            ],
            attachments=[
                {
                    "id": "att-1",
                    "entity_type": "document",
                    "entity_id": "uuid-doc-1",
                    "filename": "stray.pdf",
                    "_org": "org-uuid-acme",
                }
            ],
            download_urls={"att-1": "https://files.example.invalid/stray.pdf"},
            forbid_download_url=False,
        ),
    )
    monkeypatch.setattr(cli_module, "_check_url_reachable", lambda *a, **k: True)

    exit_code = await _run_verify(
        export_path=export,
        api_url="http://api.example.invalid",
        token="token",
        target_org="Acme Corp Test",
        check_urls=True,
        output=None,
    )

    assert exit_code == 0


@pytest.mark.asyncio
async def test_run_verify_missing_migrated_document_with_images_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An export doc with images but no migrated counterpart must fail loudly."""
    export = _copy_fixture(tmp_path)
    doc_dir = export / "documents" / "DOC-1001-3001 Test Onboarding Guide"
    doc_dir.mkdir(parents=True)
    (doc_dir / "present.png").write_bytes(b"PNG")
    (doc_dir / "index.html").write_text(
        '<p>guide</p><img src="present.png">', encoding="utf-8"
    )
    monkeypatch.setattr(cli_module, "BifrostDocsClient", make_fake_client(documents=[]))

    output = tmp_path / "fidelity.json"
    exit_code = await _run_verify(
        export_path=export,
        api_url="http://api.example.invalid",
        token="token",
        target_org="Acme Corp Test",
        check_urls=False,
        output=output,
    )

    assert exit_code == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    failures = report["organizations"][0]["embedded_images"]["failures"]
    assert len(failures) == 1
    assert failures[0]["category"] == "missing_upload"
    assert failures[0]["document_id"] == "3001"


@pytest.mark.asyncio
async def test_run_verify_missing_migrated_document_without_images_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A never-migrated document fails even when it has no images to check."""
    export = _copy_fixture(tmp_path)
    monkeypatch.setattr(cli_module, "BifrostDocsClient", make_fake_client(documents=[]))

    exit_code = await _run_verify(
        export_path=export,
        api_url="http://api.example.invalid",
        token="token",
        target_org="Acme Corp Test",
        check_urls=False,
        output=None,
    )

    assert exit_code == 1


@pytest.mark.asyncio
async def test_run_verify_sparse_attachment_records_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Migrated records without filename/entity cannot be verified: fail."""
    export = _copy_fixture(tmp_path)
    monkeypatch.setattr(
        cli_module,
        "BifrostDocsClient",
        make_fake_client(
            documents=[
                {
                    "id": "uuid-doc-1",
                    "name": "Test Onboarding Guide",
                    "metadata": {"itglue_id": "3001"},
                    "_org": "org-uuid-acme",
                }
            ],
            attachments=[
                {
                    "id": "att-no-name",
                    "entity_type": "document",
                    "entity_id": "uuid-doc-1",
                    "_org": "org-uuid-acme",
                },
                {
                    "id": "att-no-entity",
                    "entity_type": "document",
                    "filename": "stray.pdf",
                    "_org": "org-uuid-acme",
                },
            ],
        ),
    )

    output = tmp_path / "fidelity.json"
    exit_code = await _run_verify(
        export_path=export,
        api_url="http://api.example.invalid",
        token="token",
        target_org="Acme Corp Test",
        check_urls=False,
        output=output,
    )

    assert exit_code == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    failures = report["organizations"][0]["attachments"]["failures"]
    assert len(failures) == 2
    assert {failure["category"] for failure in failures} == {"unresolved_entity"}
    assert any("att-no-name" in failure["message"] for failure in failures)
    assert any("att-no-entity" in failure["message"] for failure in failures)


def test_verify_command_requires_org_or_all(tmp_path: Path) -> None:
    """The wrapper rejects missing and conflicting org selection."""
    runner = CliRunner()
    base = [
        "--export-path",
        str(tmp_path),
        "--api-url",
        "http://api.example.invalid",
        "--token",
        "token",
    ]

    assert runner.invoke(app, ["verify", *base]).exit_code == 1
    assert runner.invoke(app, ["verify", *base, "--org", "A", "--all"]).exit_code == 1
