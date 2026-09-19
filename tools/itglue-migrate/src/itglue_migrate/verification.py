"""Read-only verification helpers for migration reconciliation artifacts."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from itglue_migrate.attachments import AttachmentScanner
from itglue_migrate.document_processor import DocumentProcessor

MISSING_FILE = "missing_file"
BROKEN_API_REFERENCE = "broken_api_reference"
BROKEN_EMBEDDED_IMAGE = "broken_embedded_image"
INACCESSIBLE_URL = "inaccessible_url"
COUNT_MISMATCH = "count_mismatch"
MISSING_UPLOAD = "missing_upload"
UNEXPECTED_UPLOAD = "unexpected_upload"
UNRESOLVED_ENTITY = "unresolved_entity"
BROKEN_LINK = "broken_link"
MISSING_ORGANIZATION = "missing_organization"
API_ERROR = "api_error"

_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(\s*([^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\s*\)")

UrlChecker = Callable[[str], bool]


@dataclass(frozen=True)
class VerificationFailure:
    """Structured verification failure suitable for JSON output."""

    category: str
    message: str
    entity_type: str | None = None
    entity_id: str | None = None
    filename: str | None = None
    document_id: str | None = None
    source: str | None = None
    url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to a compact JSON-safe dictionary."""
        return {
            key: value
            for key, value in {
                "category": self.category,
                "message": self.message,
                "entity_type": self.entity_type,
                "entity_id": self.entity_id,
                "filename": self.filename,
                "document_id": self.document_id,
                "source": self.source,
                "url": self.url,
            }.items()
            if value is not None
        }


@dataclass(frozen=True)
class AttachmentReference:
    """Expected migrated attachment reference.

    The reference intentionally carries identifiers and filenames only; it does
    not carry attachment or password payload values.
    """

    entity_type: str
    entity_id: str
    filename: str
    api_id: str | None = None
    api_url: str | None = None


@dataclass(frozen=True)
class EmbeddedImageReference:
    """Expected embedded image reference from a migrated document."""

    document_id: str
    source: str
    resolved_path: Path | None = None
    migrated_url: str | None = None


@dataclass
class AttachmentVerificationResult:
    """Read-only attachment reconciliation result."""

    expected_count: int
    local_count: int
    api_count: int
    failures: list[VerificationFailure] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Whether all attachment references reconciled cleanly."""
        return not self.failures

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-safe reconciliation payload."""
        return {
            "ok": self.ok,
            "expected_count": self.expected_count,
            "local_count": self.local_count,
            "api_count": self.api_count,
            "failures": [failure.to_dict() for failure in self.failures],
        }


@dataclass
class EmbeddedImageVerificationResult:
    """Read-only embedded image reconciliation result."""

    expected_count: int
    present_count: int
    failures: list[VerificationFailure] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Whether all embedded image references are present and reachable."""
        return not self.failures

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-safe reconciliation payload."""
        return {
            "ok": self.ok,
            "expected_count": self.expected_count,
            "present_count": self.present_count,
            "failures": [failure.to_dict() for failure in self.failures],
        }


def verify_attachment_references(
    export_path: Path,
    expected: Iterable[AttachmentReference],
    *,
    scanner: AttachmentScanner | None = None,
    url_checker: UrlChecker | None = None,
) -> AttachmentVerificationResult:
    """Verify exported attachment files against migrated API references.

    Args:
        export_path: IT Glue export root to inspect.
        expected: Expected migrated attachment references.
        scanner: Optional scanner for tests or alternate export sources.
        url_checker: Optional callback for checking migrated URLs. The helper
            does not make network calls unless this callback is provided.

    Returns:
        Structured attachment verification result.
    """
    scanner = scanner or AttachmentScanner()
    references = list(expected)
    all_attachments = scanner.get_all_attachments(export_path)
    local_count = sum(
        1
        for ref in references
        if ref.filename
        in {
            path.name
            for path in all_attachments.get((ref.entity_type, ref.entity_id), [])
        }
    )
    api_count = sum(1 for ref in references if ref.api_id or ref.api_url)
    failures: list[VerificationFailure] = []

    for ref in references:
        local_files = all_attachments.get((ref.entity_type, ref.entity_id), [])
        local_names = {path.name for path in local_files}

        if ref.filename not in local_names:
            failures.append(
                VerificationFailure(
                    category=MISSING_FILE,
                    message="Expected attachment file was not found in the export.",
                    entity_type=ref.entity_type,
                    entity_id=ref.entity_id,
                    filename=ref.filename,
                )
            )

        if not ref.api_id and not ref.api_url:
            failures.append(
                VerificationFailure(
                    category=BROKEN_API_REFERENCE,
                    message="Attachment has no migrated API identifier or URL reference.",
                    entity_type=ref.entity_type,
                    entity_id=ref.entity_id,
                    filename=ref.filename,
                )
            )

        if ref.api_url and url_checker is not None:
            try:
                url_ok = url_checker(ref.api_url)
            except Exception as exc:
                url_ok = False
                message = f"Migrated attachment URL was not accessible: {exc}"
            else:
                message = "Migrated attachment URL was not accessible."

            if not url_ok:
                failures.append(
                    VerificationFailure(
                        category=INACCESSIBLE_URL,
                        message=message,
                        entity_type=ref.entity_type,
                        entity_id=ref.entity_id,
                        filename=ref.filename,
                        url=ref.api_url,
                    )
                )

    if local_count != len(references) or api_count != len(references):
        failures.append(
            VerificationFailure(
                category=COUNT_MISMATCH,
                message="Attachment counts differ between expected, local export, and API references.",
            )
        )

    return AttachmentVerificationResult(
        expected_count=len(references),
        local_count=local_count,
        api_count=api_count,
        failures=failures,
    )


def verify_embedded_images(
    expected: Iterable[EmbeddedImageReference],
    *,
    url_checker: UrlChecker | None = None,
) -> EmbeddedImageVerificationResult:
    """Verify embedded document image files and optional migrated URLs."""
    references = list(expected)
    failures: list[VerificationFailure] = []
    present_count = 0

    for ref in references:
        image_present = ref.resolved_path is not None and ref.resolved_path.is_file()

        if image_present:
            present_count += 1
        else:
            failures.append(
                VerificationFailure(
                    category=BROKEN_EMBEDDED_IMAGE,
                    message="Embedded document image file was not found.",
                    document_id=ref.document_id,
                    source=ref.source,
                )
            )

        if ref.migrated_url and url_checker is not None:
            try:
                url_ok = url_checker(ref.migrated_url)
            except Exception as exc:
                url_ok = False
                message = f"Migrated embedded image URL was not accessible: {exc}"
            else:
                message = "Migrated embedded image URL was not accessible."

            if not url_ok:
                failures.append(
                    VerificationFailure(
                        category=INACCESSIBLE_URL,
                        message=message,
                        document_id=ref.document_id,
                        source=ref.source,
                        url=ref.migrated_url,
                    )
                )

    return EmbeddedImageVerificationResult(
        expected_count=len(references),
        present_count=present_count,
        failures=failures,
    )


def extract_markdown_image_urls(content: str) -> list[str]:
    """Extract image URLs from migrated markdown document content.

    Args:
        content: Markdown text as stored in BifrostDocs.

    Returns:
        Image URLs in document order.
    """
    if not content:
        return []
    return _MARKDOWN_IMAGE_RE.findall(content)


@dataclass(frozen=True)
class MigratedAttachment:
    """An attachment record as listed by the BifrostDocs API."""

    attachment_id: str
    entity_type: str
    entity_id: str
    filename: str


@dataclass
class MigratedAttachmentReconciliation:
    """Read-only post-import attachment fidelity result."""

    expected_count: int
    migrated_count: int
    failures: list[VerificationFailure] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Whether every expected file reconciled with a migrated record."""
        return not self.failures

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-safe reconciliation payload."""
        return {
            "ok": self.ok,
            "expected_count": self.expected_count,
            "migrated_count": self.migrated_count,
            "failure_count": len(self.failures),
            "failures": [failure.to_dict() for failure in self.failures],
        }


def reconcile_migrated_attachments(
    expected: Iterable[tuple[str, str, str]],
    migrated: Iterable[tuple[str, str, str]],
    unresolved: Iterable[MigratedAttachment] = (),
) -> MigratedAttachmentReconciliation:
    """Reconcile export attachment files against migrated API records.

    Both ``expected`` and ``migrated`` use ``(entity_type, entity_id, filename)``
    triples in export vocabulary, so the caller resolves API entity UUIDs to
    IT Glue identities first. Records that cannot be resolved are reported
    separately as :data:`UNRESOLVED_ENTITY` instead of being filename-matched.

    Args:
        expected: Export-side files, one triple per file.
        migrated: Migrated records, one triple per record.
        unresolved: Migrated records whose entity could not be resolved.

    Returns:
        Structured fidelity result using ``missing_upload``,
        ``unexpected_upload``, and ``unresolved_entity`` categories.
    """
    expected_set = set(expected)
    migrated_set = set(migrated)
    failures: list[VerificationFailure] = []

    for entity_type, entity_id, filename in sorted(expected_set - migrated_set):
        failures.append(
            VerificationFailure(
                category=MISSING_UPLOAD,
                message="Export attachment file has no matching migrated record.",
                entity_type=entity_type,
                entity_id=entity_id,
                filename=filename,
            )
        )

    for entity_type, entity_id, filename in sorted(migrated_set - expected_set):
        failures.append(
            VerificationFailure(
                category=UNEXPECTED_UPLOAD,
                message="Migrated attachment has no matching export file.",
                entity_type=entity_type,
                entity_id=entity_id,
                filename=filename,
            )
        )

    for record in unresolved:
        failures.append(
            VerificationFailure(
                category=UNRESOLVED_ENTITY,
                message="Migrated attachment entity could not be matched to the export.",
                entity_type=record.entity_type,
                entity_id=record.entity_id,
                filename=record.filename,
            )
        )

    return MigratedAttachmentReconciliation(
        expected_count=len(expected_set),
        migrated_count=len(migrated_set),
        failures=failures,
    )


def verify_migrated_document_images(
    document_id: str,
    document_name: str,
    expected_count: int,
    image_urls: Iterable[str],
    *,
    url_checker: UrlChecker | None = None,
) -> EmbeddedImageVerificationResult:
    """Verify image links inside one migrated document's markdown content.

    Relative links were never rewritten to migrated URLs, so they are reported
    as :data:`BROKEN_LINK`. When fewer absolute links exist than exported
    images, the deficit is reported as :data:`MISSING_UPLOAD` with both counts
    in the message. An optional ``url_checker`` marks unreachable absolute
    links :data:`INACCESSIBLE_URL`.

    Args:
        document_id: IT Glue document ID for triage detail.
        document_name: Document name for triage detail.
        expected_count: Embedded images found in the export HTML.
        image_urls: Image URLs extracted from the migrated markdown content.
        url_checker: Optional callback for checking migrated URLs.

    Returns:
        Structured image fidelity result.
    """
    urls = list(image_urls)
    failures: list[VerificationFailure] = []
    present_count = 0
    absolute_count = 0

    for url in urls:
        if not url.lower().startswith(("http://", "https://")):
            failures.append(
                VerificationFailure(
                    category=BROKEN_LINK,
                    message=(
                        f"Migrated document '{document_name}' contains an "
                        f"image link that was never rewritten to a migrated URL."
                    ),
                    document_id=document_id,
                    source=url,
                    url=url,
                )
            )
            continue

        absolute_count += 1
        reachable = True
        if url_checker is not None:
            try:
                reachable = url_checker(url)
            except Exception:
                reachable = False
            if not reachable:
                failures.append(
                    VerificationFailure(
                        category=INACCESSIBLE_URL,
                        message=(
                            f"Migrated image URL in document '{document_name}' "
                            "was not accessible."
                        ),
                        document_id=document_id,
                        source=url,
                        url=url,
                    )
                )
        if reachable:
            present_count += 1

    if absolute_count < expected_count:
        failures.append(
            VerificationFailure(
                category=MISSING_UPLOAD,
                message=(
                    f"Document '{document_name}' references {expected_count} "
                    f"exported images but only {absolute_count} migrated "
                    "image links were found in its content."
                ),
                document_id=document_id,
            )
        )

    return EmbeddedImageVerificationResult(
        expected_count=expected_count,
        present_count=present_count,
        failures=failures,
    )


def collect_embedded_image_references(
    export_path: Path,
    documents: Iterable[dict[str, Any]],
) -> list[EmbeddedImageReference]:
    """Collect embedded image references from exported document HTML files."""
    processor = DocumentProcessor(None, export_path)  # type: ignore[arg-type]
    references: list[EmbeddedImageReference] = []

    for document in documents:
        raw_id = document.get("id")
        if not raw_id:
            continue
        document_id = str(raw_id)

        html = processor._load_document_html(  # noqa: SLF001
            document_id,
            str(document.get("name", "")),
        )
        if html is None:
            continue

        document_folder = processor._find_document_folder(document_id)  # noqa: SLF001
        for source in processor._extract_image_paths(html):  # noqa: SLF001
            resolved_path = (
                processor._resolve_image_path(document_folder, source)  # noqa: SLF001
                if document_folder is not None
                else None
            )
            references.append(
                EmbeddedImageReference(
                    document_id=document_id,
                    source=source,
                    resolved_path=resolved_path,
                )
            )

    return references
