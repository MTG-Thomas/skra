from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def _load(relative_path: str) -> dict:
    return yaml.safe_load((ROOT / relative_path).read_text(encoding="utf-8"))


def test_client_service_and_ingress_policy_share_the_named_pod_port() -> None:
    deployment = _load("kubernetes/client/deployment.yaml")
    service = _load("kubernetes/client/service.yaml")
    policy = _load(
        "kubernetes/multi-namespace/platform/network-policies/allow-ingress-to-docs.yaml"
    )

    container_ports = deployment["spec"]["template"]["spec"]["containers"][0]["ports"]
    assert container_ports == [{"containerPort": 8080, "name": "http"}]
    assert service["spec"]["ports"][0]["targetPort"] == "http"
    assert {entry["port"] for entry in policy["spec"]["ingress"][0]["ports"]} >= {
        "http",
        8000,
    }


def test_all_multi_namespace_overlays_include_the_ingress_policy() -> None:
    for environment in ("development", "staging", "production"):
        overlay = _load(f"kubernetes/multi-namespace/overlays/{environment}/kustomization.yaml")
        assert "../platform/network-policies/" in overlay["resources"]
