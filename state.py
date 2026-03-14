from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class DispatcherState:
    """Shared mutable state between event_dispatcher and the Discord bot."""
    snoozed_until: dict[str, datetime] = field(default_factory=dict)
    cancelled: set[tuple[str, str]] = field(default_factory=set)  # (event_type, trigger_minute)
