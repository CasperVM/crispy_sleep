from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class DispatcherState:
    """Shared mutable state between event_dispatcher and the Discord bot."""

    snoozed_until: dict[str, datetime] = field(default_factory=dict)
    cancelled: set[tuple[str, str]] = field(
        default_factory=set
    )  # (event_type, trigger_minute)

    def snooze(self, event_type: str, until: datetime) -> None:
        self.snoozed_until[event_type] = until
        logger.info(f"[state] snoozed {event_type} until {until.isoformat()}")

    def cancel(self, event_type: str, trigger_minute: str) -> None:
        self.cancelled.add((event_type, trigger_minute))
        logger.info(f"[state] cancelled {event_type} @ {trigger_minute}")

    def clear_snooze(self, event_type: str) -> None:
        if event_type in self.snoozed_until:
            del self.snoozed_until[event_type]
            logger.info(f"[state] snooze cleared for {event_type}")

    def clear_cancel(self, event_type: str, trigger_minute: str) -> None:
        self.cancelled.discard((event_type, trigger_minute))
        logger.info(f"[state] cancel cleared for {event_type} @ {trigger_minute}")
