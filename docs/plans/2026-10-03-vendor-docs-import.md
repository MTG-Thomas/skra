# Vendor Docs Import: Preserve Mirrored Corpora, Rehydrate via Outline/ITGlue

Date: 2026-10-03 | Issue: MTG-Thomas/skra#55 | Follow-up: MTG-Thomas/bifrost-infra#74

## Context

Two public vendor-support corpora were captured locally as test inputs for
documentation import and knowledgebase rehydration work:

- Planmeca public DokuWiki mirror: 233 raw page exports, 233 rendered XHTML
  exports, 309 same-site media files, 14 media files 403 (not archived).
- Dentsply Sirona Imaging Software and Tutorials page: 133 links, 36 page
  sections, 48 same-site assets, 1 source-page asset 404, plus large binaries
  (XIOS/XG plugin and S4 Viewer ZIPs).

The local mirror is ~1.54 GB across 830 files and must not remain laptop-only.

## Destination split

| Destination | Role |
|---|---|
| Durable object/file storage | Immutable source cache: raw mirror + manifests + large binaries |
| Outline (lab) | Staging/import validation, Markdown conversion, search and hierarchy testing |
| ITGlue / Skra docs | Curated operational articles and technician-facing vendor references |

## Durable storage layout

Each corpus is archived as one immutable directory (or bucket prefix) with a
manifest at its root:

```text
s3://vendor-corpus/<corpus-slug>/<capture-date>/
├── <corpus-slug>-<capture-date>.tar.gz   # full archive, DEEP_ARCHIVE
├── corpus-manifest.json      # CorpusManifest v1 (required)
├── pages/                    # raw page exports (DokuWiki .txt, XHTML, HTML)
├── media/                    # same-site images, CSS, small attachments
├── bin/                      # large binaries (installers, viewer ZIPs)
└── seeds/                    # derived seeds such as outline-seed.md
```

Archive procedure (run once per corpus from the machine holding the mirror):

```bash
CORPUS=planmeca-dokuwiki
DATE=2026-04-30
PREFIX=s3://vendor-corpus/${CORPUS}/${DATE}
# 1. Full archive tarball (cold copy of everything, manifest included).
tar -czf /tmp/${CORPUS}-${DATE}.tar.gz -C /path/to/mirror ${CORPUS}/
aws s3 cp /tmp/${CORPUS}-${DATE}.tar.gz ${PREFIX}/${CORPUS}-${DATE}.tar.gz \
  --storage-class DEEP_ARCHIVE
# 2. Extracted tree (working set). Per-object URIs such as
#    ${PREFIX}/bin/viewer-setup.zip MUST resolve, because dry-run reports
#    and curated articles reference large binaries by these URIs.
aws s3 sync /path/to/mirror/${CORPUS}/ ${PREFIX}/
```

The extracted tree keeps every manifest `local_path` (and every
`reference_uri` in dry-run reports) directly resolvable without fetching the
full archive; the tarball is the cold backup. Until the laptop holder runs
this upload, the manifests and tooling in this repo are the preservation
path; the physical copy step is tracked as follow-up work on
bifrost-infra#74.

## Corpus manifest (source of truth)

Schema: `api/src/services/vendor_corpus.py` (`CorpusManifest` v1). Example:
`docs/vendor-corpus/examples/sample-manifest.json`.

Every asset records `local_path`, `source_url`, `kind` (page/media/binary/seed),
and `status` (ok/forbidden/not-found/skipped/error) with the HTTP status when
known. Archived (`ok`) assets must record `bytes` and `sha256`; missing assets
must not — so the 14 Planmeca 403s and the Dentsply 404 stay visible as
explicit manifest entries instead of silent gaps.

`access_class` separates `public-only` captures from future
`authorized`/member-only captures at the corpus level. The import target guard
(`assert_import_target_allowed`) rejects authorized corpora for public targets,
and the dry-run report fails closed on disallowed targets.

## Manifest-driven import path

1. Validate the manifest (`validate_manifest`).
2. Convert archived pages to normalized Markdown:
   - DokuWiki raw exports via `dokuwiki_to_markdown` (headings, inline
     markup, internal/external links, media, lists, code blocks, tables).
   - `outline-seed.md` via `outline_seed_to_articles` (one article per H2
     section, slug-derived paths under a vendor base path).
3. Build a dry-run report (`build_dry_run_report`) and review it. The report
   lists per-asset conversion outcomes, missing assets with fetch status,
   large binaries with durable-storage reference URIs, and a `ready_for_import`
   flag. Nothing touches Outline/ITGlue during a dry run.
4. Only when the report is `ready_for_import` does a pilot import proceed to
   an Outline staging collection.

Pilot evidence for this issue is the dry-run report itself (example:
`docs/vendor-corpus/examples/sample-dry-run-report.json`), plus unit tests
covering both converters (`api/tests/unit/test_vendor_corpus.py`).

## Large binary decision

Large binaries (anything over `INLINE_BYTE_BUDGET`, 1 MB, and everything typed
`binary`) live in durable object storage only. They are never embedded in docs
payloads, never uploaded as ITGlue/Skra attachments by the import path, and
never mirrored into Outline. Converted articles reference them by durable
URI (see `reference_uri`). Rationale: the Dentsply corpus alone carries
multi-hundred-MB installer/viewer ZIPs; embedding them would bloat search
indexes, export jobs, and attachment storage for files technicians download
once. If a technician needs a binary attached to a specific ticket/article,
that stays a deliberate manual step, not an import default.

## Curated ITGlue article shape

Raw mirrored vendor material is never published verbatim. Curated
technician-facing articles derived from a corpus use this shape:

```text
Title:    <Vendor> — <Product/Area> — <Task or Symptom>
Folder:   /Vendor References/<Vendor>/
Summary:  1–2 sentences: what this covers and when to use it.
Body:     Normalized Markdown: prerequisites, steps, expected result.
Source:   Original vendor URL + corpus slug + capture date
          (e.g. "Planmeca docs, planmeca-dokuwiki @ 2026-04-30").
Binaries: Links to durable-storage URIs, never embedded files.
Review:   Owner + next review date (vendor docs drift; re-verify yearly).
```

Curation is a human pass over staged Outline articles: trim vendor marketing,
keep procedures and error tables, rewrite internal links to the curated
location, and drop anything superseded. The `Source` line preserves provenance
back to the immutable archive.

## Outline pilot plan

1. Create a staging collection per corpus (e.g. `Vendor Staging / Planmeca`).
   Public-only corpora may use the shared staging collection; authorized
   corpora get an access-restricted collection.
2. Run the dry-run report against the corpus manifest; attach the report to
   the pilot record.
3. Import converted articles to staging; validate hierarchy, search recall,
   and media rendering.
4. Curate technician-facing articles into the long-lived location; leave the
   raw staged import as the review trail, then archive it.
5. Record the outcome (imported article count, curation notes, gaps from
   403/404 assets) back on bifrost-infra#74.

## Guardrails

- No raw mirrored vendor material in public docs: public targets accept
  public-only corpora, and only curated articles leave staging.
- No real vendor content in this repo: fixtures and examples are synthetic.
- Manifests are easy to locate: one `corpus-manifest.json` per archive root,
  mirrored beside the tarball in durable storage.

## Acceptance criteria mapping

- Mirror artifacts backed up outside the laptop: archive layout + upload
  procedure above (physical upload is a laptop-holder step, tracked on
  bifrost-infra#74).
- Corpus manifests preserved and easy to locate: v1 schema, per-archive
  `corpus-manifest.json`, example manifest committed.
- Pilot import or dry-run report: dry-run report generator + example report
  + converter unit tests.
- Curated ITGlue article shape documented: "Curated ITGlue article shape".
- Large binary handling explicit: "Large binary decision" + `is_large_binary`
  enforcement in the report path.
- Follow-up linked to bifrost-infra#74: referenced here and in the module
  docstring; pilot outcome to be recorded there.
