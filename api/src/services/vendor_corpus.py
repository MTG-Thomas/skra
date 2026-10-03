"""Vendor documentation corpus import service (issue #55).

Preserves mirrored vendor-support corpora (e.g. Planmeca DokuWiki, Dentsply
support pages) as manifest-described archives in durable storage, and
rehydrates useful portions into the knowledgebase workflow through a
manifest-driven, dry-run-first import path.

Nothing in this module performs network I/O. It validates corpus manifests,
converts captured markup to normalized Markdown, and produces dry-run
import reports so a pilot import can be reviewed before anything lands in
Outline or ITGlue.

Related follow-up: MTG-Thomas/bifrost-infra#74 (Outline lab import).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator

MANIFEST_VERSION = "1"

# Assets larger than this are never embedded in a docs payload. They stay in
# durable object storage and are referenced by URI. Keeps large vendor
# binaries (plugin installers, viewer ZIPs) out of the docs app.
INLINE_BYTE_BUDGET = 1_000_000

# Import targets. Public targets must never receive authorized/member-only
# corpora or raw mirrored vendor material.
PUBLIC_TARGETS = ("outline-staging-public",)
RESTRICTED_TARGETS = ("outline-staging-authorized", "itglue-curated", "durable-storage")
KNOWN_TARGETS = PUBLIC_TARGETS + RESTRICTED_TARGETS


class AccessClass(StrEnum):
    """Capture provenance of a corpus."""

    PUBLIC_ONLY = "public-only"
    AUTHORIZED = "authorized"


class FetchStatus(StrEnum):
    """Per-asset fetch outcome recorded at mirror time."""

    OK = "ok"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not-found"
    SKIPPED = "skipped"
    ERROR = "error"


class AssetKind(StrEnum):
    """Role of an asset inside the corpus."""

    PAGE = "page"
    MEDIA = "media"
    BINARY = "binary"
    SEED = "seed"


class CorpusAsset(BaseModel):
    """One mirrored file (or one failed fetch) described by the manifest."""

    local_path: str = Field(..., min_length=1, description="Path inside the archive")
    source_url: str = Field(..., min_length=1, description="Original fetch URL")
    kind: AssetKind = AssetKind.PAGE
    status: FetchStatus = FetchStatus.OK
    http_status: int | None = Field(default=None, description="Fetch HTTP status when known")
    bytes: int | None = Field(default=None, ge=0, description="Archived byte size")
    sha256: str | None = Field(default=None, description="SHA-256 of archived bytes")
    media_type: str | None = Field(default=None, description="MIME type when known")
    note: str = Field(default="", description="Free-text capture note")

    @field_validator("sha256")
    @classmethod
    def _validate_sha256(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("sha256 must be 64 lowercase hex characters")
        return value

    @model_validator(mode="after")
    def _validate_status_consistency(self) -> CorpusAsset:
        if self.status == FetchStatus.OK:
            if self.bytes is None or self.sha256 is None:
                raise ValueError("archived (ok) assets must record bytes and sha256")
        else:
            if self.sha256 is not None:
                raise ValueError(f"{self.status.value} assets must not record a sha256")
            if self.bytes:
                raise ValueError(f"{self.status.value} assets must not record bytes")
        return self


class CorpusManifest(BaseModel):
    """Manifest describing one mirrored vendor corpus archive."""

    manifest_version: str = Field(default=MANIFEST_VERSION)
    corpus: str = Field(..., min_length=1, description="Corpus slug, e.g. planmeca-dokuwiki")
    vendor: str = Field(..., min_length=1)
    access_class: AccessClass = AccessClass.PUBLIC_ONLY
    captured_at: datetime
    source_root_url: str = Field(..., min_length=1)
    fetch_tool: str = Field(default="", description="Tool/command that captured the mirror")
    assets: list[CorpusAsset] = Field(default_factory=list)

    @field_validator("manifest_version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        if value != MANIFEST_VERSION:
            raise ValueError(f"unsupported manifest_version: {value!r}")
        return value

    @field_validator("assets")
    @classmethod
    def _validate_unique_paths(cls, assets: list[CorpusAsset]) -> list[CorpusAsset]:
        paths = [a.local_path for a in assets]
        if len(set(paths)) != len(paths):
            raise ValueError("asset local_path values must be unique")
        return assets

    def summary(self) -> dict[str, int]:
        """Count assets by fetch status."""
        counts: dict[str, int] = {"total": len(self.assets)}
        for status in FetchStatus:
            counts[status.value] = sum(1 for a in self.assets if a.status == status)
        return counts

    def missing(self) -> list[CorpusAsset]:
        """Assets that were not archived (forbidden, 404, skipped, error)."""
        return [a for a in self.assets if a.status != FetchStatus.OK]

    def large_binaries(self) -> list[CorpusAsset]:
        """Archived assets that must stay in durable storage by reference."""
        return [a for a in self.assets if is_large_binary(a)]


def validate_manifest(data: dict) -> CorpusManifest:
    """Parse and validate a raw manifest dict."""
    return CorpusManifest.model_validate(data)


def is_large_binary(asset: CorpusAsset) -> bool:
    """True when an asset must be referenced, never embedded."""
    if asset.status != FetchStatus.OK:
        return False
    if asset.kind == AssetKind.BINARY:
        return True
    return asset.bytes is not None and asset.bytes > INLINE_BYTE_BUDGET


def reference_uri(asset: CorpusAsset, archive_base_uri: str) -> str:
    """Durable-storage URI for an archived asset."""
    base = archive_base_uri.rstrip("/")
    return f"{base}/{asset.local_path.lstrip('/')}"


def assert_import_target_allowed(manifest: CorpusManifest, target: str) -> None:
    """Reject target/corpus combinations that would leak restricted material.

    Authorized (member-only) corpora may only go to restricted targets, and
    raw mirrored pages may only land in staging — never directly in a
    curated/public collection.
    """
    if target not in KNOWN_TARGETS:
        raise ValueError(f"unknown import target: {target!r}")
    if manifest.access_class == AccessClass.AUTHORIZED and target in PUBLIC_TARGETS:
        raise ValueError(f"target {target!r} cannot receive authorized corpora")


# ---------------------------------------------------------------------------
# DokuWiki -> Markdown conversion (Planmeca corpus)
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$")
_LIST_RE = re.compile(r"^( {2,})([*-])\s+(.*)$")
_TABLE_ROW_RE = re.compile(r"^\s*(\^|\|)")
_CODE_BLOCK_RE = re.compile(r"<(code|file)(\s[^>]*)?>(.*?)</\1>", re.DOTALL)
_LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_MEDIA_RE = re.compile(r"\{\{([^}|?]+)(?:\?[^}|]*)?(?:\|([^}]*))?\}\}")


def _convert_inline(text: str) -> str:
    """Convert inline DokuWiki markup to Markdown."""

    def _link(match: re.Match[str]) -> str:
        target = match.group(1).strip()
        title = (match.group(2) or "").strip()
        if "://" in target or target.startswith(("mailto:", "tel:")):
            return f"[{title or target}]({target})"
        # Internal wiki link: keep the page id as a relative reference.
        return f"[{title or target}]({target})"

    def _media(match: re.Match[str]) -> str:
        src = match.group(1).strip()
        title = (match.group(2) or "").strip()
        return f"![{title}]({src})"

    text = _MEDIA_RE.sub(_media, text)
    text = _LINK_RE.sub(_link, text)
    # Bold, italic, monospace, strikethrough. Order matters: bold first.
    text = re.sub(r"\*\*(.+?)\*\*", r"**\1**", text)
    text = re.sub(r"//(.+?)//", r"*\1*", text)
    text = re.sub(r"''(.+?)''", r"`\1`", text)
    text = re.sub(r"<del>(.+?)</del>", r"~~\1~~", text)
    return text


def _convert_table_row(line: str) -> str | None:
    """Convert one DokuWiki table row to a Markdown table row."""
    stripped = line.strip()
    if not _TABLE_ROW_RE.match(stripped):
        return None
    cells = re.split(r"[\^|]", stripped)
    cells = [_convert_inline(c.strip()) for c in cells if c.strip() != ""]
    if not cells:
        return None
    return "| " + " | ".join(cells) + " |"


def dokuwiki_to_markdown(source: str) -> str:
    """Convert DokuWiki markup to normalized Markdown.

    Covers the markup observed in the Planmeca public mirror: headings,
    bold/italic/monospace, internal and external links, embedded media,
    bullet/numbered lists, code blocks, horizontal rules, and simple tables.
    """
    lines = _CODE_BLOCK_RE.sub(lambda m: f"\n```\n{m.group(3).strip()}\n```\n", source).splitlines()

    out: list[str] = []
    prev_was_header_row = False
    for line in lines:
        if not line.strip():
            out.append("")
            prev_was_header_row = False
            continue

        heading = _HEADING_RE.match(line.strip())
        if heading:
            level = 7 - len(heading.group(1))
            out.append(f"{'#' * level} {_convert_inline(heading.group(2).strip())}")
            prev_was_header_row = False
            continue

        if line.strip() == "----":
            out.append("---")
            prev_was_header_row = False
            continue

        if line.strip().startswith("```"):
            out.append(line.strip())
            prev_was_header_row = False
            continue

        table_row = _convert_table_row(line)
        if table_row is not None:
            is_header = line.strip().startswith("^")
            out.append(table_row)
            if is_header and not prev_was_header_row:
                cells = [c.strip() for c in table_row.strip("|").split("|")]
                out.append("| " + " | ".join("---" for _ in cells) + " |")
            prev_was_header_row = is_header
            continue
        prev_was_header_row = False

        listed = _LIST_RE.match(line)
        if listed:
            indent = "  " * (len(listed.group(1)) // 2 - 1)
            marker = "1." if listed.group(2) == "-" else "*"
            out.append(f"{indent}{marker} {_convert_inline(listed.group(3).strip())}")
            continue

        out.append(_convert_inline(line.strip()))

    return "\n".join(out).strip() + "\n"


# ---------------------------------------------------------------------------
# outline-seed.md -> articles (Dentsply corpus)
# ---------------------------------------------------------------------------


class SeedArticle(BaseModel):
    """One normalized article derived from a seed document section."""

    title: str
    path: str
    content: str
    index: int = Field(ge=0)


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "untitled"


def outline_seed_to_articles(markdown: str, base_path: str = "/Vendor") -> list[SeedArticle]:
    """Split an outline-seed document into one article per H2 section.

    The leading H1 names the corpus; each `##` section becomes a standalone
    article so hierarchy and search can be validated per article in staging.
    """
    sections: list[tuple[str, list[str]]] = []
    current_title: str | None = None
    current_lines: list[str] = []

    for line in markdown.splitlines():
        heading = re.match(r"^##\s+(.*)$", line)
        if heading:
            if current_title is not None:
                sections.append((current_title, current_lines))
            current_title = heading.group(1).strip()
            current_lines = []
        elif current_title is not None:
            current_lines.append(line)

    if current_title is not None:
        sections.append((current_title, current_lines))

    base = base_path.rstrip("/")
    return [
        SeedArticle(
            title=title,
            path=f"{base}/{_slugify(title)}",
            content=("\n".join(lines).strip() + "\n") if "".join(lines).strip() else "",
            index=index,
        )
        for index, (title, lines) in enumerate(sections)
    ]


# ---------------------------------------------------------------------------
# Dry-run import reports (Outline pilot validation)
# ---------------------------------------------------------------------------


class ConversionRecord(BaseModel):
    """Outcome of converting one manifest asset to normalized Markdown."""

    local_path: str
    article_path: str = ""
    title: str = ""
    status: str = Field(default="converted", description="converted, skipped, or error")
    detail: str = ""

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str) -> str:
        if value not in ("converted", "skipped", "error"):
            raise ValueError(f"unknown conversion status: {value!r}")
        return value


def build_dry_run_report(
    manifest: CorpusManifest,
    conversions: list[ConversionRecord],
    target: str,
    archive_base_uri: str,
) -> dict:
    """Build a dry-run import report without touching the import target.

    Raises ValueError when the target is not allowed for the corpus access
    class, so an invalid pilot is a hard failure rather than a warning.
    """
    assert_import_target_allowed(manifest, target)

    by_path = {c.local_path: c for c in conversions}
    converted = [c for c in conversions if c.status == "converted"]
    errors = [c for c in conversions if c.status == "error"]
    unconverted = [
        a for a in manifest.assets if a.status == FetchStatus.OK and a.local_path not in by_path
    ]
    large = manifest.large_binaries()

    warnings: list[str] = []
    for asset in manifest.missing():
        warnings.append(
            f"{asset.local_path}: not archived ({asset.status.value}"
            + (f", http {asset.http_status}" if asset.http_status else "")
            + ")"
        )
    for asset in unconverted:
        warnings.append(f"{asset.local_path}: archived but not converted")
    for record in errors:
        warnings.append(f"{record.local_path}: conversion error ({record.detail})")
    for asset in large:
        warnings.append(
            f"{asset.local_path}: large binary stays in durable storage "
            f"({reference_uri(asset, archive_base_uri)})"
        )
    if manifest.access_class == AccessClass.AUTHORIZED:
        warnings.append("authorized corpus: staging target must not be publicly shared")

    return {
        "corpus": manifest.corpus,
        "vendor": manifest.vendor,
        "access_class": manifest.access_class.value,
        "target": target,
        "generated_at": datetime.now(UTC).isoformat(),
        "assets": manifest.summary(),
        "converted": len(converted),
        "conversion_errors": len(errors),
        "large_binaries": [
            {
                "local_path": a.local_path,
                "bytes": a.bytes,
                "reference_uri": reference_uri(a, archive_base_uri),
            }
            for a in large
        ],
        "ready_for_import": not errors and not unconverted,
        "warnings": warnings,
    }
