"""Unit tests for expiration alerts dedupe and notifications (issue #40)."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

ORG_ID = uuid4()
ASSET_ID = uuid4()


def _item(**overrides):
    from src.services.expiration import UpcomingExpiration

    base = {
        "organization_id": ORG_ID,
        "asset_id": ASSET_ID,
        "asset_display": "Wildcard Cert",
        "asset_type_id": uuid4(),
        "asset_type_name": "SSL Certificate",
        "field_key": "expires_on",
        "field_name": "Expires On",
        "expires_on": date(2026, 9, 26),
        "days_until": 7,
        "window_days": 7,
    }
    base.update(overrides)
    return UpcomingExpiration(**base)


@pytest.mark.asyncio
async def test_record_sent_inserts_new_threshold():
    """First sighting of a threshold window is recorded as sendable."""
    from src.services.expiration_alerts import ExpirationAlertService

    repo = AsyncMock()
    repo.record_sent = AsyncMock(return_value=True)
    service = ExpirationAlertService(repo)

    assert await service.maybe_record(_item()) is True
    repo.record_sent.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_sent_suppresses_repeat_threshold():
    """Re-sighting the same window suppresses duplicate alerts."""
    from src.services.expiration_alerts import ExpirationAlertService

    repo = AsyncMock()
    repo.record_sent = AsyncMock(return_value=False)
    service = ExpirationAlertService(repo)

    assert await service.maybe_record(_item()) is False


@pytest.mark.asyncio
async def test_escalating_window_records_again():
    """Moving from the 30-day to the 7-day window alerts again."""
    from src.services.expiration_alerts import ExpirationAlertService

    repo = AsyncMock()
    repo.record_sent = AsyncMock(side_effect=[True, True])
    service = ExpirationAlertService(repo)

    assert await service.maybe_record(_item(window_days=30)) is True
    assert await service.maybe_record(_item(window_days=7)) is True
    assert repo.record_sent.await_count == 2


def test_notifier_disabled_by_default_sends_nothing():
    """Without SMTP configuration the notifier only logs."""
    from src.services.expiration_alerts import ExpirationNotifier

    notifier = ExpirationNotifier(
        enabled=False, smtp_host="", smtp_port=25, sender="", recipients=[]
    )
    with patch("smtplib.SMTP") as smtp:
        notifier.notify(_item(), org_name="Acme")

    smtp.assert_not_called()


def test_notifier_sends_email_when_configured():
    """Configured SMTP delivers one message per new threshold."""
    from src.services.expiration_alerts import ExpirationNotifier

    notifier = ExpirationNotifier(
        enabled=True,
        smtp_host="mail.example.com",
        smtp_port=587,
        sender="alerts@example.com",
        recipients=["ops@example.com"],
    )
    with patch("smtplib.SMTP") as smtp:
        notifier.notify(_item(), org_name="Acme")

    instance = smtp.return_value.__enter__.return_value
    assert instance.send_message.call_count == 1
    message = instance.send_message.call_args[0][0]
    assert message["To"] == "ops@example.com"
    assert "Wildcard Cert" in message.get_content()


def test_notifier_remote_refuses_plaintext():
    """Remote SMTP without TLS stays silent instead of sending plaintext."""
    from src.services.expiration_alerts import ExpirationNotifier

    notifier = ExpirationNotifier(
        enabled=True,
        smtp_host="mail.example.com",
        smtp_port=587,
        sender="alerts@example.com",
        recipients=["ops@example.com"],
        use_starttls=False,
        use_ssl=False,
    )
    with (
        patch("smtplib.SMTP") as smtp,
        patch("smtplib.SMTP_SSL") as smtp_ssl,
    ):
        assert notifier.notify(_item(), org_name="Acme") is False

    smtp.assert_not_called()
    smtp_ssl.assert_not_called()


def test_notifier_starttls_verifies_certificate_by_default():
    """STARTTLS wraps the session in a verifying context before sending."""
    import ssl

    from src.services.expiration_alerts import ExpirationNotifier

    notifier = ExpirationNotifier(
        enabled=True,
        smtp_host="mail.example.com",
        smtp_port=587,
        sender="alerts@example.com",
        recipients=["ops@example.com"],
    )
    with patch("smtplib.SMTP") as smtp:
        assert notifier.notify(_item(), org_name="Acme") is True

    instance = smtp.return_value.__enter__.return_value
    assert instance.starttls.call_count == 1
    context = instance.starttls.call_args.kwargs["context"]
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert instance.send_message.call_count == 1


def test_notifier_ssl_and_auth():
    """Implicit TLS plus credentials logs in before sending."""
    from src.services.expiration_alerts import ExpirationNotifier

    notifier = ExpirationNotifier(
        enabled=True,
        smtp_host="mail.example.com",
        smtp_port=465,
        sender="alerts@example.com",
        recipients=["ops@example.com"],
        use_ssl=True,
        username="alerts",
        password="s3cret",
    )
    with (
        patch("smtplib.SMTP") as smtp,
        patch("smtplib.SMTP_SSL") as smtp_ssl,
    ):
        assert notifier.notify(_item(), org_name="Acme") is True

    smtp.assert_not_called()
    import ssl as ssl_module

    ssl_context = smtp_ssl.call_args.kwargs["context"]
    assert isinstance(ssl_context, ssl_module.SSLContext)
    assert ssl_context.verify_mode == ssl_module.CERT_REQUIRED
    assert ssl_context.check_hostname is True
    instance = smtp_ssl.return_value.__enter__.return_value
    instance.login.assert_called_once_with("alerts", "s3cret")
    assert instance.send_message.call_count == 1


def test_notifier_starttls_failure_fails_closed():
    """A failed STARTTLS handshake never falls back to plaintext."""
    from src.services.expiration_alerts import ExpirationNotifier

    notifier = ExpirationNotifier(
        enabled=True,
        smtp_host="mail.example.com",
        smtp_port=587,
        sender="alerts@example.com",
        recipients=["ops@example.com"],
    )
    with patch("smtplib.SMTP") as smtp:
        instance = smtp.return_value.__enter__.return_value
        instance.starttls.side_effect = RuntimeError("handshake failed")
        assert notifier.notify(_item(), org_name="Acme") is False

    assert instance.send_message.call_count == 0


def test_notifier_failure_logs_no_exception_detail(caplog):
    """SMTP failures log a bare static message: no exception text, tracebacks,
    or user-supplied org/field context."""
    import logging

    from src.services.expiration_alerts import ExpirationNotifier

    sentinel = "s3cret-password-sentinel"
    notifier = ExpirationNotifier(
        enabled=True,
        smtp_host="mail.example.com",
        smtp_port=587,
        sender="alerts@example.com",
        recipients=["ops@example.com"],
        username="alerts",
        password=sentinel,
    )
    with (
        caplog.at_level(logging.ERROR, logger="src.services.expiration_alerts"),
        patch("smtplib.SMTP") as smtp,
    ):
        instance = smtp.return_value.__enter__.return_value
        instance.starttls.side_effect = RuntimeError(f"AUTH failed: {sentinel}")
        item = _item(field_key=f"expires_on-{sentinel}")
        assert notifier.notify(item, org_name=f"Acme-{sentinel}") is False

    failure_records = [
        record
        for record in caplog.records
        if record.name == "src.services.expiration_alerts" and record.levelno == logging.ERROR
    ]
    assert len(failure_records) == 1
    record = failure_records[0]
    assert record.exc_info is None
    assert record.exc_text is None
    assert sentinel not in record.getMessage()
    for attr, value in vars(record).items():
        if attr in {"message", "msg"}:
            continue
        if isinstance(value, str):
            assert sentinel not in value, f"sentinel leaked in record.{attr}"
        elif isinstance(value, dict):
            for key, item_value in value.items():
                assert sentinel not in str(key), f"sentinel leaked in record.{attr} key"
                assert sentinel not in str(item_value), f"sentinel leaked in record.{attr}[{key!r}]"
    assert sentinel not in caplog.text
    assert "Traceback" not in caplog.text


def test_notifier_localhost_plaintext_when_unrequested():
    """Loopback delivery without TLS stays allowed for local relays."""
    from src.services.expiration_alerts import ExpirationNotifier

    notifier = ExpirationNotifier(
        enabled=True,
        smtp_host="localhost",
        smtp_port=25,
        sender="alerts@example.com",
        recipients=["ops@example.com"],
        use_starttls=False,
    )
    with patch("smtplib.SMTP") as smtp:
        assert notifier.notify(_item(), org_name="Acme") is True

    instance = smtp.return_value.__enter__.return_value
    assert instance.starttls.call_count == 0
    assert instance.send_message.call_count == 1


def test_notifier_requires_recipients():
    """Enabled SMTP without recipients stays silent."""
    from src.services.expiration_alerts import ExpirationNotifier

    notifier = ExpirationNotifier(
        enabled=True,
        smtp_host="mail.example.com",
        smtp_port=587,
        sender="alerts@example.com",
        recipients=[],
    )
    with patch("smtplib.SMTP") as smtp:
        notifier.notify(_item(), org_name="Acme")

    smtp.assert_not_called()


@pytest.mark.asyncio
async def test_service_release_deletes_claim():
    """Releasing a claim lets a later run retry the delivery."""
    from src.services.expiration_alerts import ExpirationAlertService

    repo = AsyncMock()
    repo.delete_sighting = AsyncMock(return_value=True)
    service = ExpirationAlertService(repo)

    assert await service.release(_item()) is True
    repo.delete_sighting.assert_awaited_once()


@pytest.mark.asyncio
async def test_task_skips_scan_when_notifier_disabled():
    """A disabled notifier records nothing, so later enablement still alerts."""
    from src.worker import check_expirations_task

    org_repo = AsyncMock()
    org_repo.get_all = AsyncMock()

    with (
        patch("src.worker.OrganizationRepository", return_value=org_repo),
        patch("src.worker.ExpirationAlertService") as alert_cls,
        patch("src.worker.build_expiration_notifier") as build_notifier,
        patch("src.worker.get_db_context") as db_context,
    ):
        alert_service = AsyncMock()
        alert_cls.return_value = alert_service
        notifier = build_notifier.return_value
        notifier.enabled = False
        db_session = AsyncMock()
        db_context.return_value.__aenter__ = AsyncMock(return_value=db_session)
        db_context.return_value.__aexit__ = AsyncMock(return_value=False)

        await check_expirations_task({})

    org_repo.get_all.assert_not_awaited()
    alert_service.maybe_record.assert_not_awaited()
    assert db_session.commit.await_count == 0


@pytest.mark.asyncio
async def test_task_continues_when_smtp_send_fails():
    """One failed delivery releases its claim without stopping the job."""
    from src.worker import check_expirations_task

    org = MagicMock()
    org.id = ORG_ID
    org.name = "Acme"
    org_repo = AsyncMock()
    org_repo.get_all = AsyncMock(side_effect=[[org], []])
    items = [_item(), _item(asset_id=uuid4())]

    with (
        patch("src.worker.OrganizationRepository", return_value=org_repo),
        patch(
            "src.worker.find_upcoming_expirations",
            new=AsyncMock(return_value=items),
        ),
        patch("src.worker.ExpirationAlertService") as alert_cls,
        patch("src.worker.build_expiration_notifier") as build_notifier,
        patch("src.worker.get_db_context") as db_context,
    ):
        alert_service = AsyncMock()
        alert_service.maybe_record = AsyncMock(return_value=True)
        alert_service.release = AsyncMock(return_value=True)
        alert_cls.return_value = alert_service
        notifier = build_notifier.return_value
        notifier.notify = MagicMock(side_effect=[RuntimeError("smtp down"), True])
        db_session = AsyncMock()
        db_context.return_value.__aenter__ = AsyncMock(return_value=db_session)
        db_context.return_value.__aexit__ = AsyncMock(return_value=False)

        await check_expirations_task({})

    assert notifier.notify.call_count == 2
    alert_service.release.assert_awaited_once()
    assert db_session.commit.await_count >= 1


@pytest.mark.asyncio
async def test_task_delivers_off_event_loop():
    """Blocking SMTP runs in a worker thread, never on the arq loop."""
    import asyncio
    import threading

    from src.worker import check_expirations_task

    org = MagicMock()
    org.id = ORG_ID
    org.name = "Acme"
    org_repo = AsyncMock()
    org_repo.get_all = AsyncMock(side_effect=[[org], []])
    items = [_item()]
    caller = threading.current_thread()
    delivery_threads = []

    def blocking_notify(item, org_name):
        delivery_threads.append(threading.current_thread())
        return True

    with (
        patch("src.worker.OrganizationRepository", return_value=org_repo),
        patch(
            "src.worker.find_upcoming_expirations",
            new=AsyncMock(return_value=items),
        ),
        patch("src.worker.ExpirationAlertService") as alert_cls,
        patch("src.worker.build_expiration_notifier") as build_notifier,
        patch("src.worker.get_db_context") as db_context,
    ):
        alert_service = AsyncMock()
        alert_service.maybe_record = AsyncMock(return_value=True)
        alert_cls.return_value = alert_service
        notifier = build_notifier.return_value
        notifier.enabled = True
        notifier.notify = blocking_notify
        db_session = AsyncMock()
        db_context.return_value.__aenter__ = AsyncMock(return_value=db_session)
        db_context.return_value.__aexit__ = AsyncMock(return_value=False)

        await asyncio.wait_for(check_expirations_task({}), timeout=30)

    assert len(delivery_threads) == 1
    assert all(t is not caller for t in delivery_threads)


@pytest.mark.asyncio
async def test_check_expirations_task_notifies_new_thresholds():
    """The daily job records, notifies, and counts per organization."""
    from src.worker import check_expirations_task

    org = MagicMock()
    org.id = ORG_ID
    org.name = "Acme"
    org_repo = AsyncMock()
    org_repo.get_all = AsyncMock(side_effect=[[org], []])
    items = [_item(), _item(asset_id=uuid4())]

    with (
        patch("src.worker.OrganizationRepository", return_value=org_repo),
        patch(
            "src.worker.find_upcoming_expirations",
            new=AsyncMock(return_value=items),
        ),
        patch("src.worker.ExpirationAlertService") as alert_cls,
        patch("src.worker.build_expiration_notifier") as build_notifier,
        patch("src.worker.get_db_context") as db_context,
    ):
        alert_service = AsyncMock()
        alert_service.maybe_record = AsyncMock(side_effect=[True, False])
        alert_cls.return_value = alert_service
        db_session = AsyncMock()
        db_context.return_value.__aenter__ = AsyncMock(return_value=db_session)
        db_context.return_value.__aexit__ = AsyncMock(return_value=False)

        await check_expirations_task({})

    notifier = build_notifier.return_value
    assert notifier.notify.call_count == 1
