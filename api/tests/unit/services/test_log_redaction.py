"""Sentinel redaction tests for service failure logs (issue #120).

Feeds a recognizable sentinel through representative failures in the four
services flagged by CodeQL alerts #383-#400 and asserts the captured,
configured-format log output contains no sentinel, no exception text, and
no traceback. Failure behavior (best-effort None returns) is asserted too.
"""

import io
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# Imported for side effect: registers the UserFavorite mapper so SQLAlchemy
# relationship configuration works when this module runs standalone
# (user.py references it under TYPE_CHECKING only).
import src.models.orm.user_favorite  # noqa: F401
from src.models.enums import AuditAction
from src.services.audit_service import AuditService
from src.services.oauth_config_service import OAuthConfigService

# Obviously fake probe value: low entropy, never credential-shaped, so static
# scanners ignore it while grep-style assertions still catch any leak.
SENTINEL = "log-redaction-sentinel-9f27"

# App text format, mirroring logging.basicConfig in src/main.py.
APP_TEXT_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


@pytest.fixture
def formatted_stream():
    """Capture root log output rendered through the configured text format."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter(APP_TEXT_FORMAT))
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        yield stream
    finally:
        root.removeHandler(handler)


def assert_no_leak(caplog, stream, *extra_texts):
    """No sentinel, traceback, or exception rendering in captured output."""
    rendered = stream.getvalue()
    assert SENTINEL not in rendered
    service_records = [r for r in caplog.records if r.name.startswith("src.services.")]
    assert service_records, "expected service log records to be captured"
    for record in service_records:
        assert record.exc_info is None and record.exc_text is None
        assert SENTINEL not in record.getMessage()
        for value in vars(record).values():
            if isinstance(value, str):
                assert SENTINEL not in value
    for text in extra_texts:
        assert SENTINEL not in text


@pytest.mark.unit
async def test_enqueue_index_failure_redacts(caplog, formatted_stream):
    """indexing_queue failure: sentinel exception + sentinel ID stay out."""
    from src.services import indexing_queue

    failure = RuntimeError(f"redis down: password={SENTINEL}")
    with (
        patch.object(indexing_queue, "create_pool", new=AsyncMock(side_effect=failure)),
        caplog.at_level(logging.DEBUG),
    ):
        result = await indexing_queue.enqueue_index_entity(
            "password", f"entity-{SENTINEL}", f"org-{SENTINEL}"
        )
    assert result is None
    assert_no_leak(caplog, formatted_stream)


@pytest.mark.unit
async def test_enqueue_remove_failure_redacts(caplog, formatted_stream):
    """indexing_queue removal failure: same redaction guarantee."""
    from src.services import indexing_queue

    failure = RuntimeError(f"redis down: token {SENTINEL}")
    with (
        patch.object(indexing_queue, "create_pool", new=AsyncMock(side_effect=failure)),
        caplog.at_level(logging.DEBUG),
    ):
        result = await indexing_queue.enqueue_remove_entity("document", f"entity-{SENTINEL}")
    assert result is None
    assert_no_leak(caplog, formatted_stream)


@pytest.mark.unit
async def test_enqueue_success_keeps_static_event(caplog, formatted_stream):
    """Success path still logs a static event with the entity type only."""
    from src.services import indexing_queue

    pool = AsyncMock()
    with (
        patch.object(indexing_queue, "create_pool", new=AsyncMock(return_value=pool)),
        caplog.at_level(logging.DEBUG),
    ):
        result = await indexing_queue.enqueue_index_entity("password", "some-id", "some-org")
    assert result is None
    assert "Enqueued index job" in formatted_stream.getvalue()
    assert "some-id" not in formatted_stream.getvalue()


@pytest.mark.unit
async def test_search_index_failure_redacts(caplog, formatted_stream):
    """search_indexing failure: sentinel exception never reaches logs."""
    from src.services import search_indexing

    db = MagicMock()
    failure = RuntimeError(f"queue refused: secret={SENTINEL}")
    with (
        patch.object(search_indexing, "is_indexing_enabled", new=AsyncMock(return_value=True)),
        patch(
            "src.services.indexing_queue.enqueue_index_entity",
            new=AsyncMock(side_effect=failure),
        ),
        caplog.at_level(logging.DEBUG),
    ):
        result = await search_indexing.index_entity_for_search(db, "password", uuid4(), uuid4())
    assert result is None
    assert_no_leak(caplog, formatted_stream)


@pytest.mark.unit
async def test_search_remove_failure_redacts(caplog, formatted_stream):
    """search_indexing removal failure: same redaction guarantee."""
    from src.services import search_indexing

    db = MagicMock()
    failure = RuntimeError(f"queue refused: {SENTINEL}")
    with (
        patch(
            "src.services.indexing_queue.enqueue_remove_entity",
            new=AsyncMock(side_effect=failure),
        ),
        caplog.at_level(logging.DEBUG),
    ):
        result = await search_indexing.remove_entity_from_search(db, "document", uuid4())
    assert result is None
    assert_no_leak(caplog, formatted_stream)


@pytest.mark.unit
async def test_oauth_decrypt_failure_redacts(caplog, formatted_stream):
    """oauth decrypt failure: sentinel exception + key stay out, None returned."""
    from src.services import oauth_config_service

    stored = SimpleNamespace(value_json={"value": "undecryptable"})
    db_result = SimpleNamespace(scalar_one_or_none=lambda: stored)
    db = MagicMock()
    db.execute = AsyncMock(return_value=db_result)
    failure = ValueError(f"bad Fernet token {SENTINEL}")
    with (
        patch.object(oauth_config_service, "decrypt_secret", side_effect=failure),
        caplog.at_level(logging.DEBUG),
    ):
        result = await OAuthConfigService(db)._get_secret_value(f"client-secret-{SENTINEL}")
    assert result is None
    assert_no_leak(caplog, formatted_stream)
    assert "OAuth secret decrypt failed" in formatted_stream.getvalue()


@pytest.mark.unit
async def test_audit_log_redacts_identifiers(caplog, formatted_stream):
    """audit log lines carry the static event, never record identifiers."""
    db = MagicMock()
    db.add = MagicMock()
    db.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None))
    service = AuditService(db)
    entity_id = uuid4()
    organization_id = uuid4()
    with caplog.at_level(logging.DEBUG):
        result = await service.log(
            AuditAction.VIEW, "password", entity_id, organization_id=organization_id
        )
    assert result is None
    db.add.assert_called_once()
    assert_no_leak(caplog, formatted_stream)
    assert "Audit:" in formatted_stream.getvalue()
    assert str(entity_id) not in formatted_stream.getvalue()
    assert str(organization_id) not in formatted_stream.getvalue()


@pytest.mark.unit
async def test_audit_dedupe_hit_redacts_identifiers(caplog, formatted_stream):
    """audit dedupe-hit line also omits the entity identifier."""
    db = MagicMock()
    db.add = MagicMock()
    db.execute = AsyncMock(
        return_value=SimpleNamespace(scalar_one_or_none=lambda: SimpleNamespace())
    )
    service = AuditService(db)
    actor = MagicMock()
    actor.user_id = uuid4()
    actor.api_key_id = None
    entity_id = uuid4()
    with caplog.at_level(logging.DEBUG):
        result = await service.log(
            AuditAction.VIEW, "password", entity_id, actor=actor, dedupe_seconds=60
        )
    assert result is None
    db.add.assert_not_called()
    assert_no_leak(caplog, formatted_stream)
    assert "Audit dedupe:" in formatted_stream.getvalue()
    assert str(entity_id) not in formatted_stream.getvalue()
