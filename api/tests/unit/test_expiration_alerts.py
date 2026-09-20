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
async def test_task_releases_claim_when_notifier_disabled():
    """A disabled notifier records nothing permanent for future runs."""
    from src.worker import check_expirations_task

    org = MagicMock()
    org.id = ORG_ID
    org.name = "Acme"
    org_repo = AsyncMock()
    org_repo.get_all = AsyncMock(side_effect=[[org], []])
    items = [_item()]

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
        notifier.notify = MagicMock(return_value=False)
        db_session = AsyncMock()
        db_context.return_value.__aenter__ = AsyncMock(return_value=db_session)
        db_context.return_value.__aexit__ = AsyncMock(return_value=False)

        await check_expirations_task({})

    alert_service.release.assert_awaited_once()
    assert db_session.commit.await_count >= 1


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
