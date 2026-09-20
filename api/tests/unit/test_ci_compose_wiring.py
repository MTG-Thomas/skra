"""Guards for CI compose wiring (test-client-profile Playwright step).

The auth-smoke step once hardcoded the pre-rename compose network
(bifrost-docs-test_default), failing with "network not found" after the
project was renamed to skra-test. These tests pin the fix: no stale
project network literal may reappear, and the step must derive the
network from the live compose project config.
"""

from pathlib import Path

CI_YML = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"


def _auth_smoke_block() -> str:
    text = CI_YML.read_text(encoding="utf-8")
    start = text.index("Run auth smoke suite")
    return text[start:]


def test_no_stale_compose_network_literal():
    """No --network flag may reference the pre-rename test network."""
    text = CI_YML.read_text(encoding="utf-8")

    network_flags = [line for line in text.splitlines() if "--network" in line]
    assert network_flags, "expected a --network flag in CI"
    for line in network_flags:
        assert "bifrost-docs-test" not in line
        assert "bifrost_docs_test" not in line


def test_auth_smoke_derives_network_from_compose_config():
    """The Playwright container joins the compose-resolved network."""
    block = _auth_smoke_block()

    assert "docker compose -f docker-compose.test.yml config --format json" in block
    assert '--network "${TEST_NETWORK}"' in block
