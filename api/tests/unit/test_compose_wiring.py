"""Wiring tests for compose service definitions (VM101 smoke findings).

Two real boot defects escaped to the VM: the worker service missed
``SKRA_DATABASE_URL_SYNC`` (mandatory Settings field, so the worker
exited on validation), and the dev client healthcheck shelled out to
``wget``, absent from the node:20-slim dev image. These tests parse the
compose files as text (no yaml dependency) and pin both contracts.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
DEV = (ROOT / "docker-compose.dev.yml").read_text(encoding="utf-8")
TEST = (ROOT / "docker-compose.test.yml").read_text(encoding="utf-8")


def _service_block(text: str, name: str) -> str:
    """Return the raw text of one top-level service block."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if re.match(rf"^  {name}:$", line))
    end = next(
        (i for i in range(start + 1, len(lines)) if re.match(r"^  \S", lines[i])),
        len(lines),
    )
    return "\n".join(lines[start:end])


def test_settings_services_define_both_database_urls():
    """Every service booting Settings must provide both DB URL vars."""
    for text, services in (
        (BASE, ("api", "worker", "init")),
        (DEV, ("api", "worker", "init")),
        (TEST, ("api", "init", "test-runner")),
    ):
        for service in services:
            block = _service_block(text, service)
            if "SKRA_DATABASE_URL:" not in block:
                continue
            assert "SKRA_DATABASE_URL_SYNC:" in block, service


def _uncommented(block: str) -> str:
    """Strip full-line and trailing comments so docs cannot trip the checks."""
    return "\n".join(line.split("#", 1)[0] for line in block.splitlines())


def test_node_image_clients_probe_without_wget():
    """node-based client images probe via node; wget exists only for nginx."""
    for text, name in ((DEV, "dev"), (TEST, "test")):
        code = _uncommented(_service_block(text, "client"))
        assert "wget" not in code, name
        assert "node -e" in code, name


def test_base_client_keeps_nginx_probe():
    """The prod nginx image has no node, so it keeps the wget probe."""
    code = _uncommented(_service_block(BASE, "client"))

    assert "wget" in code
    assert "http://127.0.0.1/health" in code


def test_dev_client_probes_vite_health_proxy():
    """The dev override targets the Vite /health proxy on port 80."""
    code = _uncommented(_service_block(DEV, "client"))

    assert "http://127.0.0.1/health" in code
