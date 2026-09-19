# OS CVEs in the published API image (issue #108)

Inventory date: 2026-09-19. Scanner: Trivy 0.74.0 (pinned container image).
Target digest: `ghcr.io/mtg-thomas/bifrost-docs-api@sha256:bafb39087e475a27fb3a3c4a8500526d821ad6417ce4ef55e7ad1d48f2334c9b`
(revision `bfdf348`, debian 13.7). Gate flags plus unfixed included:
`--severity HIGH,CRITICAL --scanners vuln --vuln-type os,library`.

## Headline

- With `--ignore-unfixed` (the CI gate): **0 findings**. Gate stays green.
- Without it (the SARIF upload, which has no severity/ignore-unfixed
  filter): **52 rows, 12 unique HIGH CVEs, 0 CRITICAL, all with no fixed
  version**. Python packages: 0. The repeated SARIF alerts (#750 and
  siblings) are re-reports of these same 12 across successive image scans,
  not independent vulnerabilities.

## Unique findings

| CVE | Severity | Packages (installed version) | Fixed |
|---|---|---|---|
| CVE-2026-76642, CVE-2026-78408, CVE-2026-78409, CVE-2026-78410 | HIGH | util-linux + bsdutils, libblkid1, liblastlog2-2, libmount1, libsmartcols1, libuuid1, login, mount (all 2.41.5-0+deb13u1) | none |
| CVE-2026-12064, CVE-2026-8286, CVE-2026-8458, CVE-2026-8927 | HIGH | curl, libcurl4t64 (8.14.1-2+deb13u5) | none |
| CVE-2026-54369 | HIGH | libacl1 (2.3.2-2+b1) | none |
| CVE-2025-69720 | HIGH | libncursesw6, libtinfo6, ncurses-base, ncurses-bin (6.5+20250216-2) | none |
| CVE-2026-16742 | HIGH | libsystemd0, libudev1 (257.13-1~deb13u1) | none |
| CVE-2026-9538 | HIGH | perl-base (5.40.1-6+deb13u1) | none |

## Reachability in the non-root runtime

Runtime user is `app` (non-root); the entrypoint is uvicorn serving the
FastAPI app from `/opt/venv`. The app never shells out: no `subprocess`,
no `os.system`/`os.exec` call sites invoke mount, login, su, perl, tput,
or curl. Suid binaries (`/usr/bin/su`, `/bin/mount`, `/bin/umount`, …)
exist on disk but are unreachable without code execution first — and code
execution already implies full compromise through easier paths. No shell,
no SSH, no cron in the image. Residual risk is therefore limited to a
vulnerability reachable through data the app itself parses with these
libraries (libcurl is never loaded by Python deps — no pycurl in
`uv.lock`; libacl/libncurses/libsystemd reach the process only via libc
dynamic linkage, not via called functionality).

## Removal (this lane)

- **curl + libcurl4t64 (8 rows)**: removed. Nothing installed depends on
  them (`apt-cache rdepends --installed` empty; no pycurl in the lock).
  Verified on a VM101 build of this lane (`cve108-api:verify`, compose
  project `cve108`): `command -v curl` empty, dpkg knows neither package,
  HEALTHCHECK config carries the python probe, and Trivy 0.74.0 reports
  44 rows vs 52 on the published digest — exactly the 8 curl/libcurl4t64
  rows gone, 0 added, fixed-vulnerability gate exit 0.
  The only consumer was the HEALTHCHECK, rewritten to an equivalent
  `python -c` urllib probe (exit 0 only on HTTP 200; verified as USER app
  in the published image: 200→0, 404→1, refused→1). Compose `api`
  healthchecks converted identically.
- **Not removable**: util-linux, mount, login (Priority required,
  util-linux Essential: yes); ncurses-bin, perl-base (Essential: yes);
  libsystemd0/libudev1, libacl1, ncurses libs (required by libc-linked
  dependents; `apt-get purge` would break the base system). Verified with
  `dpkg-query` priority/essential flags inside the digest.

## Residual and monitoring

Remaining unfixed rows (~44) stay visible in SARIF and are **not
dismissed**: re-scan the published digest after each Debian security
update window and drop this file's inventory when fixed versions land.
The `perl-base --only-upgrade` line in the Dockerfile already applies
fixed revisions automatically on rebuild; the same applies to these
packages the day fixes publish.
