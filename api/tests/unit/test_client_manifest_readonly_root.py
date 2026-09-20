"""Guards for the client Deployment read-only root filesystem (Trivy KSV-0014).

The nginx container must run with `readOnlyRootFilesystem: true`, with only
the writable scratch paths nginx:alpine actually needs backed by emptyDir:

- /tmp — pid file (the image bakes in `pid /tmp/nginx.pid;`)
- /var/cache/nginx — proxy/client-body temp files

Logs need no mount (the image symlinks access/error logs to
stdout/stderr), and /usr/share/nginx/html + /etc/nginx stay read-only.
uid 101, port 8080, and the probes must be preserved.
"""

from pathlib import Path

DEPLOYMENT = Path(__file__).resolve().parents[3] / "kubernetes" / "client" / "deployment.yaml"


def _text() -> str:
    return DEPLOYMENT.read_text(encoding="utf-8")


def test_readonly_root_filesystem_enabled():
    """Trivy KSV-0014: the client container must set readOnlyRootFilesystem."""
    text = _text()

    assert "readOnlyRootFilesystem: true" in text
    assert "readOnlyRootFilesystem: false" not in text


def test_nginx_scratch_mounts_are_emptydir():
    """/tmp and /var/cache/nginx are mounted from emptyDir volumes."""
    text = _text()

    assert "mountPath: /tmp" in text
    assert "mountPath: /var/cache/nginx" in text
    # Each named scratch volume is an emptyDir (no hostPath/persistent claim).
    assert text.count("emptyDir: {}") == 2
    assert "hostPath" not in text


def test_nonroot_uid_and_port_preserved():
    """read-only hardening must not change uid 101 or the 8080 serving port."""
    text = _text()

    assert "runAsUser: 101" in text
    assert "runAsGroup: 101" in text
    assert "runAsNonRoot: true" in text
    assert "containerPort: 8080" in text
    assert "fsGroup: 101" in text  # kubelet chowns the emptyDirs to uid 101
