"""Security regressions for multi-namespace NetworkPolicy peers."""

import os
from pathlib import Path


def _repo_root() -> Path:
    """Locate the repository root from local and containerized test runs."""
    env_root = os.environ.get("REPO_ROOT")
    if env_root and (Path(env_root) / "kubernetes").is_dir():
        return Path(env_root)
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "kubernetes").is_dir():
            return candidate
    raise FileNotFoundError("kubernetes directory not found above test file")


POLICY_DIR = (
    _repo_root() / "kubernetes" / "multi-namespace" / "platform" / "network-policies"
)

RESTRICTED_PEERS = {
    "allow-docs-to-bifrost.yaml": (
        "skra",
        "app.kubernetes.io/component: api",
    ),
    "allow-ingress-to-docs.yaml": (
        "bifrost-platform",
        "app.kubernetes.io/name: ingress-nginx",
    ),
    "allow-ingress-to-bifrost.yaml": (
        "bifrost-platform",
        "app.kubernetes.io/name: ingress-nginx",
    ),
}


def _from_block(policy: str) -> str:
    """Return the first ingress rule's source-peer block."""
    lines = policy.splitlines()
    start = lines.index("    - from:") + 1
    end = lines.index("      ports:", start)
    return "\n".join(lines[start:end])


def test_restricted_ingress_peers_require_namespace_and_pod_labels():
    """Each peer must AND its namespace and pod selectors in one item."""
    for filename, (namespace_name, pod_label) in RESTRICTED_PEERS.items():
        policy = (POLICY_DIR / filename).read_text(encoding="utf-8")
        peer = _from_block(policy)

        assert peer.count("        - namespaceSelector:") == 1, filename
        assert "        - podSelector:" not in peer, filename
        assert "          podSelector:" in peer, filename
        assert f"              app.kubernetes.io/name: {namespace_name}" in peer
        assert f"              {pod_label}" in peer
