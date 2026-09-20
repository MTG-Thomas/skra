"""
Expiration alert dedupe and email notification (issue #40).

The daily worker job records each newly-crossed threshold window via
:class:`ExpirationAlertService` and delivers one email per new window via
:class:`ExpirationNotifier`. SMTP stays disabled unless configured.
"""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Any

from src.services.expiration import UpcomingExpiration

logger = logging.getLogger(__name__)


class ExpirationAlertService:
    """Deduplicates expiration alerts against sent-alert sightings."""

    def __init__(self, repository: Any):
        self._repository = repository

    async def maybe_record(self, item: UpcomingExpiration) -> bool:
        """
        Record a sighting of an item's threshold window.

        Returns True when this is the first sighting (caller should
        notify), False when the window already alerted (suppress).
        """
        return await self._repository.record_sent(
            organization_id=item.organization_id,
            asset_id=item.asset_id,
            field_key=item.field_key,
            window_days=item.window_days,
        )


@dataclass
class ExpirationNotifier:
    """Sends expiration alert emails over SMTP when configured."""

    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    sender: str = ""
    recipients: list[str] = field(default_factory=list)

    def notify(self, item: UpcomingExpiration, org_name: str) -> bool:
        """
        Send one alert email for an item's threshold window.

        Returns True when an email was delivered, False when the
        notifier is disabled or incomplete (logged, no send attempted).
        """
        if not self.enabled or not self.smtp_host or not self.sender or not self.recipients:
            logger.info(
                "Expiration notifier disabled; skipping alert",
                extra={
                    "organization": org_name,
                    "asset_id": str(item.asset_id),
                    "field_key": item.field_key,
                },
            )
            return False

        if item.days_until >= 0:
            timing = f"expires in {item.days_until} days"
        else:
            timing = f"expired {-item.days_until} days ago"

        message = EmailMessage()
        message["Subject"] = f"[{org_name}] Expiring asset: {item.asset_display}"
        message["From"] = self.sender
        message["To"] = ", ".join(self.recipients)
        message.set_content(
            f"{item.asset_display} ({item.asset_type_name}) in organization "
            f"{org_name}: field '{item.field_name}' {timing} "
            f"(expires {item.expires_on})."
        )

        with smtplib.SMTP(self.smtp_host, self.smtp_port) as smtp:
            smtp.send_message(message)

        logger.info(
            "Expiration alert sent",
            extra={
                "organization": org_name,
                "asset_id": str(item.asset_id),
                "field_key": item.field_key,
            },
        )
        return True


def build_expiration_notifier(settings: Any = None) -> ExpirationNotifier:
    """Build the notifier from application settings (disabled by default)."""
    from src.config import get_settings

    config = settings or get_settings()
    recipients = [
        address.strip()
        for address in str(config.smtp_recipients or "").split(",")
        if address.strip()
    ]
    return ExpirationNotifier(
        enabled=bool(config.smtp_enabled),
        smtp_host=config.smtp_host or "",
        smtp_port=config.smtp_port,
        sender=config.smtp_sender or "",
        recipients=recipients,
    )
