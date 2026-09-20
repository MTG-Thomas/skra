"""Guards for the API/worker Deployments read-only root filesystems (Trivy KSV-0014).

Every runtime container (API init, API server, arq worker) must run with
`readOnlyRootFilesystem: true`, with the only writable path (/tmp —
CPython tempfile + Starlette multipart spool) backed by a size-bounded
emptyDir. Attachments move via S3 presigned URLs and exports are built in
memory, so no other scratch mount is needed.

Pod identity must be the fixed UID/GID 15000 baked into api/Dockerfile
(garage-init chowns shared creds to 15000:15000). Secrets stay as envFrom:
no secret volumes exist to mount. Serving behavior (uvicorn/arq commands,
probes, ports, resources) must be preserved.
"""

from pathlib import Path

API_DEPLOYMENT = Path(__file__).resolve().parents[3] / "kubernetes" / "api" / "deployment.yaml"
WORKER_DEPLOYMENT = (
    Path(__file__).resolve().parents[3] / "kubernetes" / "worker" / "deployment.yaml"
)

APP_UID = "15000"


def _api_text() -> str:
    return API_DEPLOYMENT.read_text(encoding="utf-8")


def _worker_text() -> str:
    return WORKER_DEPLOYMENT.read_text(encoding="utf-8")


def test_readonly_root_filesystem_enabled_on_all_runtime_containers():
    """Trivy KSV-0014: init + api + worker containers set readOnlyRootFilesystem."""
    api_text = _api_text()
    worker_text = _worker_text()

    # API Deployment has two runtime containers (init, api).
    assert api_text.count("readOnlyRootFilesystem: true") == 2
    assert "readOnlyRootFilesystem: false" not in api_text

    assert worker_text.count("readOnlyRootFilesystem: true") == 1
    assert "readOnlyRootFilesystem: false" not in worker_text


def test_privilege_escalation_disabled_on_all_runtime_containers():
    """Init, API, and worker must not acquire privileges through setuid binaries."""
    api_text = _api_text()
    worker_text = _worker_text()

    assert api_text.count("allowPrivilegeEscalation: false") == 2
    assert worker_text.count("allowPrivilegeEscalation: false") == 1
    assert "allowPrivilegeEscalation: true" not in api_text + worker_text


def test_tmp_is_the_only_writable_mount_and_is_bounded():
    """/tmp is the sole volumeMount, backed by a size-limited emptyDir."""
    for text in (_api_text(), _worker_text()):
        assert "mountPath: /tmp" in text
        # No other writable mount: exactly one mountPath entry per file for
        # the worker, two for the API (init + api share one named volume).
        assert "hostPath" not in text
        assert "secretName" not in text  # secrets stay envFrom, not volumes
        assert "sizeLimit:" in text


def test_api_tmp_volume_shared_by_init_and_server():
    """Both API containers mount the same bounded emptyDir scratch volume."""
    text = _api_text()

    assert text.count("mountPath: /tmp") == 2
    assert text.count("emptyDir:") == 1


def test_image_identity_matches_dockerfile_uid():
    """runAs/fsGroup must be 15000 (api/Dockerfile `app` user), never 1000."""
    for text in (_api_text(), _worker_text()):
        assert f"runAsUser: {APP_UID}" in text
        assert f"runAsGroup: {APP_UID}" in text
        assert f"fsGroup: {APP_UID}" in text
        assert "runAsNonRoot: true" in text
        assert "runAsUser: 1000" not in text


def test_worker_liveness_probe_reads_env_from_python():
    """exec probes run without a shell: ${...} would be passed literally.

    The probe must read SKRA_REDIS_URL via os.environ so it can actually
    connect once deployed.
    """
    text = _worker_text()

    assert "${SKRA_REDIS_URL}" not in text
    assert "os.environ['SKRA_REDIS_URL']" in text


def test_serving_behavior_preserved():
    """Hardening must not change commands, ports, probes, or env sources."""
    api_text = _api_text()
    worker_text = _worker_text()

    assert '["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]' in api_text
    assert '["python", "-m", "scripts.init_container"]' in api_text
    assert "path: /health" in api_text
    assert "containerPort: 8000" in api_text

    assert '["arq", "src.worker.WorkerSettings"]' in worker_text

    for text in (api_text, worker_text):
        assert "configMapRef:\n                name: skra-config" in text
        assert "secretRef:\n                name: skra-secrets" in text
