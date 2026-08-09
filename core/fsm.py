"""Hero Loop state machine — kernel organ. Windows/channels are config-owned
parameters, never constants (owner law: owner-data lives in config).

The FSM is the deterministic FLOOR: its tick names the floor action when a
deadline passes. The kernel may, at a junction, let the model choose among
bounded alternatives (extend once, switch channel, escalate now) — but if the
model is down or slow, the floor stands. Every transition is a receipt.

Escalation WALKS the tree: ESCALATED carries its own deadline; no callback
within the window moves to the next contact. An exhausted tree re-arms from
the top with a longer window — the state never sits without a firing route
(harness lesson #10: a route is something that actually fires).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

IDLE = "IDLE"
CHECKIN_SENT = "CHECKIN_SENT"
ENGAGED = "ENGAGED"
SILENCE_1 = "SILENCE_1"
SILENCE_2 = "SILENCE_2"
ESCALATED = "ESCALATED"
RESOLVED = "RESOLVED"

STATES = (IDLE, CHECKIN_SENT, ENGAGED, SILENCE_1, SILENCE_2, ESCALATED, RESOLVED)
TERMINAL = (IDLE, ENGAGED, RESOLVED)  # states allowed to hold no deadline

_LEGAL = {
    IDLE: {CHECKIN_SENT},
    CHECKIN_SENT: {ENGAGED, SILENCE_1},
    ENGAGED: {IDLE, CHECKIN_SENT},
    SILENCE_1: {CHECKIN_SENT, SILENCE_2, ENGAGED},
    SILENCE_2: {ESCALATED, ENGAGED},
    ESCALATED: {RESOLVED, ESCALATED},   # ESCALATED->ESCALATED = next contact
    RESOLVED: {IDLE},
}


class IllegalTransition(Exception):
    pass


@dataclass
class HeroLoop:
    now: Callable[[], datetime]
    on_transition: Callable[[str, str, str], None]
    # config-owned windows (minutes) — injected by the kernel from config.json
    ack_window: float = 60
    retry_window: float = 30
    escalation_window: float = 10
    escalation_rearm_window: float = 30
    channels: tuple = ("app", "voice_call")

    state: str = IDLE
    channel_idx: int = 0
    contact_idx: int = 0
    deadline: datetime | None = None
    entered_at: datetime | None = None
    extended: bool = False          # extend-once affordance for bounded choice
    armed_at: datetime | None = None  # when the current expectation was armed

    def _move(self, new: str, reason: str) -> None:
        if new not in _LEGAL[self.state]:
            raise IllegalTransition(f"{self.state} -> {new} ({reason})")
        old, self.state = self.state, new
        self.entered_at = self.now()
        self.on_transition(old, new, reason)

    def _arm(self, minutes: float) -> None:
        self.armed_at = self.now()
        self.deadline = self.armed_at + timedelta(minutes=minutes)

    # --- entry points -----------------------------------------------------
    def checkin_sent(self, channel: str, kind: str = "greeting") -> None:
        """A prompt that expects a response was delivered (morning greeting OR
        med reminder — the all-day silence net: every prompt arms a window)."""
        if self.state == SILENCE_1:
            self._move(CHECKIN_SENT, f"retry_channel:{channel}")
            self._arm(self.retry_window)
        elif self.state in (IDLE, ENGAGED):
            self._move(CHECKIN_SENT, f"{kind}:{channel}")
            self._arm(self.ack_window)
        self.extended = False

    def heartbeat(self, source: str) -> None:
        if self.state in (CHECKIN_SENT, SILENCE_1, SILENCE_2):
            self._move(ENGAGED, f"heartbeat:{source}")
            self.deadline = None
        elif self.state == ESCALATED:
            # the elder's own touch is the strongest evidence there is —
            # it resolves an escalation just as a family callback does
            self._move(RESOLVED, f"elder_heartbeat:{source}")
            self.deadline = None
        elif self.state == ENGAGED:
            self.entered_at = self.now()

    def family_confirmed(self, who: str) -> None:
        if self.state == ESCALATED:
            self._move(RESOLVED, f"callback:{who}")
            self.deadline = None

    def settle(self) -> None:
        if self.state in (ENGAGED, RESOLVED):
            self._move(IDLE, "episode_closed")
            self.channel_idx = 0
            self.contact_idx = 0
            self.deadline = None

    def extend(self) -> bool:
        """Bounded-choice affordance: push the current deadline once."""
        if self.extended or self.deadline is None:
            return False
        self.extended = True
        self.deadline = self.deadline + timedelta(minutes=self.retry_window)
        return True

    def escalated(self) -> None:
        """escalate_tree receipt: family notification actually went out.
        Arms the callback window — ESCALATED always holds a firing route."""
        if self.state == SILENCE_2:
            self._move(ESCALATED, f"family_notified:contact_{self.contact_idx}")
            self._arm(self.escalation_window)

    def escalate_next(self, n_contacts: int) -> str:
        """Callback window expired. Walk the tree; wrap with a longer window."""
        self.contact_idx += 1
        if self.contact_idx >= n_contacts:
            self.contact_idx = 0
            self._move(ESCALATED, "tree_exhausted_rearmed")
            self._arm(self.escalation_rearm_window)
            return "rearmed"
        self._move(ESCALATED, f"next_contact:{self.contact_idx}")
        self._arm(self.escalation_window)
        return f"contact_{self.contact_idx}"

    def force_silence2(self, reason: str) -> None:
        """Bounded choice 'escalate_now': walk the legal chain immediately."""
        if self.state == CHECKIN_SENT:
            self._move(SILENCE_1, reason)
        if self.state == SILENCE_1:
            self._move(SILENCE_2, reason)
            self.deadline = None

    # --- the tick: names the FLOOR action at a junction ---------------------
    def tick(self) -> dict | None:
        """Returns a junction dict {name, floor, options} or None. The kernel
        gates/chooses/acts; only receipts re-enter as events."""
        if self.deadline is None or self.now() < self.deadline:
            return None
        if self.state == CHECKIN_SENT:
            was_retry = self.channel_idx > 0
            self._move(SILENCE_1, "no_ack")
            if was_retry or self.channel_idx + 1 >= len(self.channels):
                self._move(SILENCE_2, "channels_exhausted")
                self.deadline = None
                return {"name": "silence_2", "floor": "escalate_tree", "options": ["escalate_tree"]}
            next_ch = self.channels[self.channel_idx + 1]
            self.deadline = None
            options = [f"retry:{next_ch}", "escalate_now"]
            if not self.extended:
                options.append("extend_once")
            return {"name": "silence_1", "floor": f"retry:{next_ch}", "options": options}
        if self.state == SILENCE_1:
            self._move(SILENCE_2, "no_ack_after_retry")
            self.deadline = None
            return {"name": "silence_2", "floor": "escalate_tree", "options": ["escalate_tree"]}
        if self.state == ESCALATED:
            self.deadline = None
            return {"name": "escalation_timeout", "floor": "escalate_next", "options": ["escalate_next"]}
        return None

    def apply_choice(self, junction: str, choice: str, n_contacts: int) -> str:
        """Apply a (gated, validated) junction choice. Returns the action the
        kernel must now perform, '' if none."""
        if junction == "silence_1":
            if choice.startswith("retry:"):
                self.channel_idx += 1
                return choice
            if choice == "escalate_now":
                self.force_silence2("choice:escalate_now")
                return "escalate_tree"
            if choice == "extend_once":
                # re-arm the ack window once; stay in SILENCE_1 poised to retry
                self._arm(self.retry_window)
                self.extended = True
                return ""
        if junction == "silence_2":
            return "escalate_tree"
        if junction == "escalation_timeout":
            return f"escalate:{self.escalate_next(n_contacts)}"
        return ""

    def snapshot(self) -> dict:
        return {
            "state": self.state,
            "channel": self.channels[min(self.channel_idx, len(self.channels) - 1)],
            "contact_idx": self.contact_idx,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "entered_at": self.entered_at.isoformat() if self.entered_at else None,
            "extended": self.extended,
        }
