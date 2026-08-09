"""Injectable clock — the demo red line lives here.

The demo console may inject TIME and SCENARIOS, never behavior. Every kernel
component reads time from this clock and only this clock; the production
build runs WallClock, the demo runs DemoClock with timeskip. Nothing else
in the system may call time.time()/datetime.now() for decision-making, so
the agent the judges watch is the real agent — just living on a faster day.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

SGT = timezone(timedelta(hours=8))


class WallClock:
    def now(self) -> datetime:
        return datetime.now(SGT)

    def ts(self) -> float:
        return time.time()


class DemoClock:
    """Wall-clock cadence with an injectable offset.

    skip_to(hh, mm) jumps the virtual day forward to the next occurrence of
    that time; advance(minutes) jumps relative. Between injections time flows
    at 1x, so scheduled triggers fire through the same code path as production.
    """

    def __init__(self, start: datetime | None = None) -> None:
        self._lock = threading.Lock()
        base = start or datetime.now(SGT)
        self._offset = base - datetime.now(SGT)

    def now(self) -> datetime:
        with self._lock:
            return datetime.now(SGT) + self._offset

    def ts(self) -> float:
        return self.now().timestamp()

    def advance(self, minutes: float) -> datetime:
        with self._lock:
            self._offset += timedelta(minutes=minutes)
        return self.now()

    def skip_to(self, hour: int, minute: int = 0) -> datetime:
        with self._lock:
            current = datetime.now(SGT) + self._offset
            target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= current:
                target += timedelta(days=1)
            self._offset += target - current
        return self.now()

    def reset(self) -> datetime:
        with self._lock:
            self._offset = timedelta(0)
        return self.now()
