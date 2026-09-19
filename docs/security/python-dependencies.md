# Python dependency update path (API)

This note covers issues #82 and #84. The published API/worker image installs
its venv from `api/uv.lock`, so lockfile changes control what ships.

## Change dependencies

1. Edit version bounds in `api/pyproject.toml` (`dependencies`).
2. Re-resolve the lockfile from `api/`:
   `uv lock` (installs mismatch fail the image build via `--locked`).
3. Sanity-check without touching the lock: `uv lock --check`.
4. Open one PR containing both the `pyproject.toml` and `uv.lock` changes
   (dependabot's uv-group PRs already do this, e.g. #80).

## How each consumer proves versions

| Consumer | Mechanism |
|---|---|
| Published image (`api/Dockerfile` builder) | `uv sync --locked --no-dev` into `/opt/venv`; build fails on lock drift. |
| CI backend checks | `pip install -e ".[dev]"` from `pyproject.toml` (unpinned floors). |
| Local dev/test venv | Project `.venv` via `pip install -e ./api[dev]` or `uv sync --dev`. |

## Verify an image-affecting bump

1. Build: `docker build ./api` (CI builds on every main push).
2. Confirm the built version (pip is not installed in the runtime image):
   `docker run --rm --entrypoint /opt/venv/bin/python <img> -c "from importlib.metadata import version; print(version(\"<pkg>\"))"`.
3. Run the shared gate from the repo root (same flags as CI):
   `./scripts/trivy-image-gate.sh <image-ref> [trivy-bin]`.
4. VM-gated acceptance (startup, authenticated smoke, gate) runs on VM 101
   or an equivalent isolated runner — coordinate release with the owning lane.
