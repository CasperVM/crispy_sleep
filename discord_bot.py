"""
Discord bot for crispy_sleep.
DMs owner + optional member with ahead-of-time routine nudges and sleep/wake logging.
No server needed — communicates via DMs only.

Requires: discord.py (uv add discord.py)

Slash commands (DM the bot):
  /sleep              — log sleep time now (owner only)
  /wake               — log wake time now (owner only)
  /cancel <routine>   — cancel upcoming/ongoing winddown or sunrise
  /start <routine>    — start a routine immediately
"""
from __future__ import annotations

import asyncio
import enum
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

import discord
from discord import app_commands

from db import get_conn, log_sleep_event, is_scheduling_enabled
from env_conf import (
    DISCORD_BOT_TOKEN,
    DISCORD_OWNER_ID,
    DISCORD_MEMBER_ID,
    SLEEP_TARGET_HOUR,
    SLEEP_DURATION_H,
    DISCORD_NUDGE_ADVANCE_MIN,
)
from scheduler import get_next_event
from state import DispatcherState

logger = logging.getLogger(__name__)


class DelayReason(str, enum.Enum):
    SCREEN_TIME   = "screen_time"   # phone / doomscrolling
    GAMING_SOCIAL = "gaming_social" # gaming or social online
    SOCIAL_OUT    = "social_out"    # out (bar, event, dinner)
    NO_REASON     = "no_reason"     # just didn't feel like it
    WORK          = "work"          # work ran over
    SICK          = "sick"          # sick / unwell
    LIFE_HAPPENED = "life_happened" # catch-all non-actionable


class DelayCategory(str, enum.Enum):
    ACTIONABLE      = "actionable"
    SEMI_ACTIONABLE = "semi_actionable"
    NON_ACTIONABLE  = "non_actionable"


_REASON_CATEGORY: dict[DelayReason, DelayCategory] = {
    DelayReason.SCREEN_TIME:   DelayCategory.ACTIONABLE,
    DelayReason.GAMING_SOCIAL: DelayCategory.ACTIONABLE,
    DelayReason.SOCIAL_OUT:    DelayCategory.ACTIONABLE,
    DelayReason.NO_REASON:     DelayCategory.ACTIONABLE,
    DelayReason.WORK:          DelayCategory.SEMI_ACTIONABLE,
    DelayReason.SICK:          DelayCategory.NON_ACTIONABLE,
    DelayReason.LIFE_HAPPENED: DelayCategory.NON_ACTIONABLE,
}


_ALLOWED_IDS: frozenset[int] = frozenset(
    uid for uid in (DISCORD_OWNER_ID, DISCORD_MEMBER_ID) if uid
)
_WAKE_HOUR = (SLEEP_TARGET_HOUR + SLEEP_DURATION_H) % 24


class DelayReasonView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=300)
        self.owner_id = owner_id

    async def _log(self, interaction: discord.Interaction, reason: DelayReason):
        log_sleep_event(str(self.owner_id), "delay", delay_reason=reason.value)
        await interaction.response.edit_message(content=f"Logged: {reason.value}", view=None)
        self.stop()

    @discord.ui.button(label="📱 Phone/scroll", style=discord.ButtonStyle.secondary, row=0)
    async def screen_time(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._log(interaction, DelayReason.SCREEN_TIME)

    @discord.ui.button(label="🎮 Gaming/social", style=discord.ButtonStyle.secondary, row=0)
    async def gaming_social(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._log(interaction, DelayReason.GAMING_SOCIAL)

    @discord.ui.button(label="🍻 Out", style=discord.ButtonStyle.secondary, row=0)
    async def social_out(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._log(interaction, DelayReason.SOCIAL_OUT)

    @discord.ui.button(label="😶 Just didn't feel like it", style=discord.ButtonStyle.secondary, row=0)
    async def no_reason(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._log(interaction, DelayReason.NO_REASON)

    @discord.ui.button(label="💼 Work ran over", style=discord.ButtonStyle.secondary, row=1)
    async def work(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._log(interaction, DelayReason.WORK)

    @discord.ui.button(label="🤒 Sick", style=discord.ButtonStyle.secondary, row=1)
    async def sick(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._log(interaction, DelayReason.SICK)

    @discord.ui.button(label="🎲 Life happened", style=discord.ButtonStyle.secondary, row=1)
    async def life_happened(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._log(interaction, DelayReason.LIFE_HAPPENED)


class NudgeView(discord.ui.View):
    def __init__(self, event_type: str, trigger_at: datetime, state: DispatcherState):
        super().__init__(timeout=DISCORD_NUDGE_ADVANCE_MIN * 60 + 300)
        self.event_type = event_type
        self.trigger_at = trigger_at
        self.state = state

    def _key(self) -> tuple[str, str]:
        return (self.event_type, self.trigger_at.strftime("%Y-%m-%d %H:%M"))

    async def _ask_reason(self, interaction: discord.Interaction):
        if interaction.user.id == DISCORD_OWNER_ID:
            await interaction.followup.send(
                "Why the delay?",
                view=DelayReasonView(DISCORD_OWNER_ID),
                ephemeral=True,
            )

    @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Starting on time.", ephemeral=True)
        self.stop()

    @discord.ui.button(label="⏰ +15 min", style=discord.ButtonStyle.blurple)
    async def delay_15(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.state.snoozed_until[self.event_type] = self.trigger_at + timedelta(minutes=15)
        await interaction.response.send_message("Delayed 15 min.", ephemeral=True)
        await self._ask_reason(interaction)
        self.stop()

    @discord.ui.button(label="⏰ +30 min", style=discord.ButtonStyle.blurple)
    async def delay_30(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.state.snoozed_until[self.event_type] = self.trigger_at + timedelta(minutes=30)
        await interaction.response.send_message("Delayed 30 min.", ephemeral=True)
        await self._ask_reason(interaction)
        self.stop()

    @discord.ui.button(label="❌ Skip tonight", style=discord.ButtonStyle.red)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.state.cancelled.add(self._key())
        await interaction.response.send_message("Skipped tonight.", ephemeral=True)
        await self._ask_reason(interaction)
        self.stop()


async def _consume_queue(
    client: discord.Client,
    notify_queue: asyncio.Queue,
    state: DispatcherState,
):
    while True:
        item = await notify_queue.get()
        event_type: str = item["event_type"]
        trigger_at: datetime = item["trigger_at"]

        minutes_until = max(0, int(
            (trigger_at - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds() / 60
        ))
        msg = (
            f"🌙 **{event_type.capitalize()}** in {minutes_until} min "
            f"({trigger_at.strftime('%H:%M')})\n"
            f"Target sleep: {SLEEP_TARGET_HOUR:02d}:00 → wake {_WAKE_HOUR:02d}:00 ({SLEEP_DURATION_H}h)"
        )

        for uid in _ALLOWED_IDS:
            try:
                user = await client.fetch_user(uid)
                await user.send(msg, view=NudgeView(event_type, trigger_at, state))
            except Exception as e:
                logger.warning(f"[Discord] Failed to DM {uid}: {e}")

        notify_queue.task_done()


def _register_commands(
    tree: app_commands.CommandTree,
    state: DispatcherState,
    somneo,
    routines: dict[str, Callable],
):
    @tree.command(name="sleep", description="Log sleep time now (owner only)")
    async def cmd_sleep(interaction: discord.Interaction):
        if interaction.user.id != DISCORD_OWNER_ID:
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return
        log_sleep_event(str(DISCORD_OWNER_ID), "sleep")
        await interaction.response.send_message("😴 Sleep logged.", ephemeral=True)

    @tree.command(name="wake", description="Log wake time now (owner only)")
    async def cmd_wake(interaction: discord.Interaction):
        if interaction.user.id != DISCORD_OWNER_ID:
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return
        log_sleep_event(str(DISCORD_OWNER_ID), "wake")
        await interaction.response.send_message("☀️ Wake logged.", ephemeral=True)

    @tree.command(name="cancel", description="Cancel upcoming or ongoing routine")
    @app_commands.describe(routine="winddown or sunrise")
    async def cmd_cancel(interaction: discord.Interaction, routine: str):
        if interaction.user.id not in _ALLOWED_IDS:
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return
        if routine not in routines:
            await interaction.response.send_message(
                f"Unknown routine. Options: {', '.join(routines)}", ephemeral=True
            )
            return
        # Cancel upcoming occurrence
        ev = get_next_event(routine)
        if ev:
            key = (routine, datetime.fromisoformat(ev["trigger_at"]).strftime("%Y-%m-%d %H:%M"))
            state.cancelled.add(key)
        # Cancel ongoing (if currently running) via settings flag
        with get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, '1')",
                (f"cancel_{routine}",),
            )
        await interaction.response.send_message(f"❌ {routine} cancelled.", ephemeral=True)

    @tree.command(name="scheduling", description="Enable or disable scheduling (owner only)")
    @app_commands.describe(state="on or off")
    async def cmd_scheduling(interaction: discord.Interaction, state: str):
        if interaction.user.id != DISCORD_OWNER_ID:
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return
        if state not in ("on", "off"):
            enabled = is_scheduling_enabled()
            await interaction.response.send_message(
                f"Scheduling is currently **{'on' if enabled else 'off'}**. Use `/scheduling on` or `/scheduling off`.",
                ephemeral=True,
            )
            return
        value = "1" if state == "on" else "0"
        with get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('scheduling_enabled', ?)",
                (value,),
            )
        await interaction.response.send_message(
            f"{'✅' if state == 'on' else '⛔'} Scheduling **{state}**.", ephemeral=True
        )

    @tree.command(name="start", description="Start a routine now")
    @app_commands.describe(routine="winddown, sunrise, or coffee")
    async def cmd_start(interaction: discord.Interaction, routine: str):
        if interaction.user.id not in _ALLOWED_IDS:
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return
        if routine not in routines:
            await interaction.response.send_message(
                f"Unknown routine. Options: {', '.join(routines)}", ephemeral=True
            )
            return
        asyncio.create_task(routines[routine](somneo))
        await interaction.response.send_message(f"▶️ {routine} started.", ephemeral=True)


async def run_discord_bot(
    notify_queue: asyncio.Queue,
    state: DispatcherState,
    somneo,
    routines: dict[str, Callable],
):
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)

    _register_commands(tree, state, somneo, routines)

    @client.event
    async def on_ready():
        await tree.sync()
        logger.info(f"[Discord] Bot ready: {client.user}")
        asyncio.create_task(_consume_queue(client, notify_queue, state))

    await client.start(DISCORD_BOT_TOKEN)
