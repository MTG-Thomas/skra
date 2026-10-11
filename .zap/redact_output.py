"""Copy ZAP output to an upload-safe directory while redacting the scan token."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

REDACTION = b"[REDACTED]"


def redact_bytes(content: bytes, secret: bytes) -> bytes:
    """Remove both the token and its bearer-header form from content."""
    if not secret:
        raise ValueError("refusing to redact with an empty secret")

    bearer = b"Bearer " + secret
    return content.replace(bearer, REDACTION).replace(secret, REDACTION)


def write_redacted(source: Path, destination: Path, secret: bytes) -> None:
    """Write one redacted file without following a generated symlink."""
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"refusing non-regular ZAP output: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(redact_bytes(source.read_bytes(), secret))


def create_safe_artifacts(
    source_dir: Path,
    destination_dir: Path,
    console_source: Path,
    console_destination: Path,
    secret: bytes,
) -> None:
    """Create a sanitized artifact tree and console log using atomic publication."""
    if destination_dir.exists():
        raise FileExistsError(f"destination already exists: {destination_dir}")

    staging_dir = Path(
        tempfile.mkdtemp(prefix=f".{destination_dir.name}-", dir=destination_dir.parent)
    )
    console_fd, console_staging_name = tempfile.mkstemp(
        prefix=f".{console_destination.name}-", dir=console_destination.parent
    )
    os.close(console_fd)
    console_staging = Path(console_staging_name)

    try:
        for source in source_dir.rglob("*"):
            if source.is_dir():
                continue
            write_redacted(source, staging_dir / source.relative_to(source_dir), secret)

        write_redacted(console_source, console_staging, secret)
        staging_dir.replace(destination_dir)
        console_staging.replace(console_destination)
    except BaseException:
        shutil.rmtree(staging_dir, ignore_errors=True)
        console_staging.unlink(missing_ok=True)
        raise


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print(
            "usage: redact_output.py SOURCE_DIR DESTINATION_DIR CONSOLE_SOURCE CONSOLE_DESTINATION",
            file=sys.stderr,
        )
        return 2

    token = os.environ.get("SKRA_ZAP_API_TOKEN", "").encode()
    if not token:
        print("SKRA_ZAP_API_TOKEN is required for output redaction", file=sys.stderr)
        return 2

    create_safe_artifacts(Path(argv[1]), Path(argv[2]), Path(argv[3]), Path(argv[4]), token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
