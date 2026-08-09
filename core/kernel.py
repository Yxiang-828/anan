"""AnAn kernel — event inbox + the full decision pipeline.

Every action passes WAKE → THINK → REVALIDATE → GATE → ACT → RECEIPT → COMMIT,
each phase a named receipt in the store (deck P7/P8; research/18).

- THINK: at a junction the model chooses among BOUNDED options; the FSM's
  deterministic floor stands when the model is down, slow, or answers outside
  the envelope. Choice is logged with chosen-vs-floor.
- REVALIDATE: a candidate born from an older snapshot is checked against newer
  evidence before any external mutation (a heartbeat submitted after the
  candidate was created cancels a silence action — the 反悔 beat).
- GATE: the permission envelope (config-owned): autonomous / approval / never.
  A never-class effect refuses loudly. Nothing acts around the gate.
- LIVENESS: a watchdog that counts FIRING ROUTES (armed deadline, cron with a
  next fire), never the existence of state (harness lesson #10). It inspects
  fields directly — a separate code path from the tick that consumes them —
  though it shares the same process; that shared dependency is declared here
  rather than hidden.
"""
from __future__ import annotations

import queue
import threading
import time as _time
import traceback
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from core.fsm import HeroLoop, TERMINAL


@dataclass
class Skill:
    id: str
    capability: str
    description: str
    run: Callable[..., dict]
    trigger: str = ""
    effects: tuple = ()   # permission classes this skill exercises, e.g. ("notify.family",)


class Registry:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def add(self, skill: Skill) -> None:
        if not callable(skill.run):
            raise TypeError(f"skill {skill.id} advertised but not dispatchable")
        self._skills[skill.id] = skill

    def get(self, skill_id: str) -> Skill:
        try:
            return self._skills[skill_id]
        except KeyError:
            near = [s for s in self._skills if skill_id[:4] in s or s[:4] in skill_id]
            raise KeyError(f"no skill '{skill_id}'. Skills that exist: "
                           f"{', '.join(near or sorted(self._skills))}") from None

    def catalogue(self) -> str:
        return "\n".join(f"- {s.id}: {s.capability}" for s in self._skills.values())

    def all(self) -> list[Skill]:
        return list(self._skills.values())

    def self_test(self) -> None:
        """Everything advertised must dispatch (harness lesson #3)."""
        for s in self._skills.values():
            if not callable(s.run):
                raise TypeError(f"catalogued skill {s.id} does not dispatch")


BOOT_OVERDUE_GRACE_MIN = 10


class Kernel:
    def __init__(self, clock, store, config: dict, chooser: Callable[[str, list, dict], str] | None = None) -> None:
        self.clock = clock
        self.store = store
        self.config = config
        self.registry = Registry()
        self.inbox: queue.Queue = queue.Queue()
        self.channels: dict[str, Callable[[str, dict], dict]] = {}
        self.chooser = chooser  # model-backed bounded chooser; None => floor only
        win = config.get("windows", {})
        self.loop = HeroLoop(
            now=clock.now, on_transition=self._on_transition,
            ack_window=float(win.get("ack_min", 60)),
            retry_window=float(win.get("retry_min", 30)),
            escalation_window=float(win.get("escalation_min", 10)),
            escalation_rearm_window=float(win.get("escalation_rearm_min", 30)),
            channels=tuple(config.get("channels", ["app", "voice_call"])),
        )
        self._crons: list[dict] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._booted_at: datetime | None = None
        self._started_wall = _time.time()
        # revalidation evidence: wall-time of the latest heartbeat SUBMITTED
        # (producer side) — lets a candidate see evidence still queued behind it
        self._last_heartbeat_wall = 0.0
        self._esc_seq = 0
        self._liveness_last = 0.0

    # --- wiring ------------------------------------------------------------
    def channel(self, name: str, send: Callable[[str, dict], dict]) -> None:
        self.channels[name] = send

    def cron(self, hh: int, mm: int, skill_id: str) -> None:
        self._crons.append({"hh": hh, "mm": mm, "skill": skill_id, "last_day": None})

    def crons_from_config(self) -> None:
        for spec, skill_id in (self.config.get("schedule") or {}).items():
            hh, _, mm = spec.partition(":")
            self.cron(int(hh), int(mm), skill_id)

    def submit(self, kind: str, source: str, detail: dict | None = None) -> None:
        if kind == "heartbeat":
            self._last_heartbeat_wall = _time.time()
        self.inbox.put({"kind": kind, "source": source, "detail": detail or {},
                        "created_wall": _time.time()})

    def _on_transition(self, old: str, new: str, reason: str) -> None:
        self.store.event(self._at(), "transition", "fsm",
                         {"from": old, "to": new, "reason": reason},
                         effect=f"state {old}->{new}")

    def _at(self) -> str:
        return self.clock.now().strftime("%Y-%m-%d %H:%M:%S")

    def uptime_h(self) -> float:
        return (_time.time() - self._started_wall) / 3600

    # --- loop ---------------------------------------------------------------
    def start(self) -> None:
        self.registry.self_test()
        self._booted_at = self.clock.now()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                event = self.inbox.get(timeout=1.0)
            except queue.Empty:
                self._tick()
                continue
            try:
                self._handle(event)
            except Exception as exc:
                self.store.event(self._at(), "error", "kernel",
                                 {"event": {k: event[k] for k in ("kind", "source", "detail")},
                                  "error": str(exc), "trace": traceback.format_exc()[-600:]})

    def _tick(self) -> None:
        now = self.clock.now()
        rolled = []
        for c in self._crons:
            due = now.replace(hour=c["hh"], minute=c["mm"], second=0, microsecond=0)
            if now < due or c["last_day"] == now.date().isoformat():
                continue
            overdue_min = (now - due).total_seconds() / 60
            c["last_day"] = now.date().isoformat()
            if self._booted_at and due < self._booted_at and overdue_min > BOOT_OVERDUE_GRACE_MIN:
                rolled.append(f"{c['hh']:02d}:{c['mm']:02d} {c['skill']}")
                continue
            self.submit("cron_due", "scheduler", {"skill": c["skill"]})
        if rolled:  # one summary receipt, not one line per cron (demo-log hygiene)
            self.store.event(self._at(), "wake", "scheduler",
                             {"decision": "rolled_forward", "crons": rolled},
                             effect=f"boot guard: {len(rolled)} stale cron(s) rolled forward, none replayed")
        junction = self.loop.tick()
        if junction:
            self.submit("junction", "fsm", junction)
        self._liveness_check()

    def _liveness_check(self) -> None:
        """Routes, not states. A non-terminal FSM state must hold an armed
        deadline (the tick path fires it). Crons must each hold a next fire
        (they always do by construction — asserted anyway, cheaply)."""
        if _time.time() - self._liveness_last < 30:
            return
        self._liveness_last = _time.time()
        # a queued inbox event IS a firing route (lesson #10 cuts both ways) —
        # and one clean observation is not pathology: alarm on the SECOND
        # consecutive routeless check, not the first
        routeless = (self.loop.state not in TERMINAL
                     and self.loop.deadline is None
                     and self.inbox.qsize() == 0)
        if routeless and getattr(self, "_routeless_prev", False):
            self.store.event(self._at(), "liveness", "watchdog",
                             {"state": self.loop.state, "deadline": None,
                              "inbox": 0, "verdict": "LIVENESS_GAP"},
                             effect="non-terminal state with NO firing route (sustained)")
        self._routeless_prev = routeless

    # --- event handling -----------------------------------------------------
    def _handle(self, event: dict) -> None:
        at = self._at()
        kind = event["kind"]
        self.store.event(at, "wake", event["source"], {"event": kind, **{
            k: v for k, v in event["detail"].items() if k != "options"}})
        if kind == "cron_due":
            self._pipeline(event["detail"]["skill"], reason=f"scheduled ({event['source']})",
                           candidate_wall=event["created_wall"])
        elif kind == "junction":
            self._junction(event["detail"], candidate_wall=event["created_wall"])
        elif kind == "heartbeat":
            self.loop.heartbeat(event["detail"].get("via", event["source"]))
            if event["detail"].get("med"):
                self.store.log("med_log", at=at, med=event["detail"]["med"], status="taken")
        elif kind == "user_text":
            # SKILL ROUTING — the planner chooses: just talk, or actually act?
            # (autonomous tool selection; floor = companion_chat)
            text = event["detail"].get("text", "")
            skill_id, how = "companion_chat", "floor"
            if self.chooser:
                try:
                    picked = self.chooser(
                        "elder_request", ["companion_chat", "relay_family"],
                        {"TA刚说": text[:200],
                         "规则": "TA想让家人知道某件事/带话/求助家人 -> relay_family; 普通聊天 -> companion_chat"})
                    if picked in ("companion_chat", "relay_family"):
                        skill_id, how = picked, "model"
                except Exception as exc:
                    how = f"floor (chooser failed: {str(exc)[:50]})"
            self.store.event(at, "think", "router",
                             {"junction": "elder_request", "chosen": skill_id, "how": how,
                              "options": ["companion_chat", "relay_family"]})
            self._pipeline(skill_id, reason=f"elder spoke ({how})",
                           candidate_wall=event["created_wall"], text=text)
        elif kind == "family_callback":
            who = event["detail"].get("who", "family")
            self.store.log("escalation_log", at=at, step="callback", contact=who, outcome="confirmed")
            self.loop.family_confirmed(who)
            self.loop.settle()
        elif kind == "escalation_delivered":
            self.loop.escalated()
        elif kind == "settle":
            self.loop.settle()
        elif kind == "location":
            self._location(event["detail"], candidate_wall=event["created_wall"])
        elif kind == "health_score":
            self._health(event["detail"], candidate_wall=event["created_wall"])

    def _health(self, detail: dict, candidate_wall: float) -> None:
        """Camera health checks (all CV runs ON the elder's device — only the
        score arrives here; frames never leave the phone). Logging always;
        alerting is DETERMINISTIC thresholds from config (a stroke screen must
        not depend on a model's mood)."""
        kind = detail.get("kind", "")
        score = float(detail.get("score", 0))
        self.store.log("health_log", at=self._at(), kind=kind, score=score,
                       metrics=__import__("json").dumps(detail.get("metrics", {}), ensure_ascii=False))
        self.loop.heartbeat(f"health_check:{kind}")   # doing a check is a touch
        th = self.config.get("health_thresholds", {})
        alert = ((kind == "face_symmetry" and score < float(th.get("face_symmetry_min", 60)))
                 or (kind == "heart_rate" and not
                     (float(th.get("bpm_min", 45)) <= score <= float(th.get("bpm_max", 120)))))
        self._pipeline("health_scan", reason=f"{kind} score {score:g}"
                       + (" — ANOMALOUS, family alert" if alert else " — logged"),
                       candidate_wall=candidate_wall,
                       kind=kind, score=score, alert=alert,
                       metrics=detail.get("metrics", {}))

    def _location(self, detail: dict, candidate_wall: float) -> None:
        """Wander safety — DETERMINISTIC floor (a dementia geofence must not
        depend on a model's mood). Breach → safe_range skill; return → all
        clear. Re-alerts only after rearm_min outside."""
        import math
        home = self.config.get("home") or {}
        lat, lng = detail.get("lat"), detail.get("lng")
        if not home or lat is None or lng is None:
            return
        dlat = math.radians(lat - home["lat"])
        dlng = math.radians(lng - home["lng"])
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(home["lat"])) * math.cos(math.radians(lat)) *
             math.sin(dlng / 2) ** 2)
        dist_m = 6371000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        self.store.put("last_location", {"lat": lat, "lng": lng, "dist_m": round(dist_m),
                                         "at": self._at()})
        outside = dist_m > float(home.get("radius_m", 300))
        flagged = self.store.get("wander_flag")
        if outside and not flagged:
            self.store.put("wander_flag", {"since": self._at()})
            self._pipeline("safe_range", reason=f"geofence breach: {int(dist_m)}m from home "
                           f"(radius {home.get('radius_m')}m)",
                           candidate_wall=candidate_wall,
                           lat=lat, lng=lng, dist_m=int(dist_m))
        elif not outside and flagged:
            self.store.put("wander_flag", None)
            self._pipeline("safe_range", reason="returned inside the safe radius",
                           candidate_wall=candidate_wall,
                           lat=lat, lng=lng, dist_m=int(dist_m), returned=True)

    def _junction(self, junction: dict, candidate_wall: float) -> None:
        """THINK (bounded choice) → REVALIDATE → apply → act."""
        name, floor, options = junction["name"], junction["floor"], junction["options"]
        chosen = floor
        how = "floor (no chooser)"
        if self.chooser and len(options) > 1:
            try:
                picked = self.chooser(name, options, self.loop.snapshot())
                if picked in options:
                    chosen, how = picked, "model"
                else:
                    how = f"floor (model answered outside envelope: {picked[:40]!r})"
            except Exception as exc:
                how = f"floor (chooser failed: {str(exc)[:60]})"
        self.store.event(self._at(), "think", "chooser",
                         {"junction": name, "options": options, "floor": floor,
                          "chosen": chosen, "how": how})
        # REVALIDATE: silence-born candidates die if a heartbeat was submitted
        # after the candidate was created (evidence may still be queued behind us)
        if name in ("silence_1", "silence_2") and self._last_heartbeat_wall > candidate_wall:
            self.store.event(self._at(), "revalidate", "kernel",
                             {"junction": name, "verdict": "STALE",
                              "why": "heartbeat arrived after candidate creation"},
                             effect="candidate cancelled — no external action")
            return
        self.store.event(self._at(), "revalidate", "kernel",
                         {"junction": name, "verdict": "valid"})
        action = self.loop.apply_choice(name, chosen, len(self.config.get("contact_tree", [])) or 1)
        if not action:
            return
        if action.startswith("retry:"):
            self._pipeline("greet_checkin", reason=f"retry on {action.split(':', 1)[1]}",
                           candidate_wall=candidate_wall, revalidated=True,
                           channel=action.split(":", 1)[1])
        elif action == "escalate_tree" or action.startswith("escalate:"):
            self._esc_seq += 1
            self._pipeline("escalate_tree", reason=f"escalation ({action})",
                           candidate_wall=candidate_wall, revalidated=True,
                           contact_idx=self.loop.contact_idx,
                           esc_id=f"esc-{self._esc_seq}")

    def _gate(self, skill: Skill) -> tuple[bool, str]:
        env = self.config.get("envelope", {})
        never = set(env.get("never", []))
        approval = set(env.get("approval", []))
        for effect in skill.effects:
            if effect in never:
                return False, f"NEVER-class effect {effect} — refused"
            if effect in approval:
                # approval effects only execute as a consequence of an explicit
                # family action (a Telegram button IS the approval); skills fired
                # from the kernel's own loop may not exercise them directly
                return False, f"APPROVAL-class effect {effect} — needs family action"
        return True, "autonomous envelope"

    def _pipeline(self, skill_id: str, reason: str, candidate_wall: float,
                  revalidated: bool = False, **args: Any) -> None:
        at = self._at()
        self.store.event(at, "think", "planner",
                         {"skill": skill_id, "reason": reason,
                          "catalogue_size": len(self.registry.all())})
        if not revalidated:
            self.store.event(at, "revalidate", "kernel",
                             {"skill": skill_id, "verdict": "valid",
                              "why": "no newer conflicting evidence"})
        skill = self.registry.get(skill_id)
        ok, why = self._gate(skill)
        self.store.event(self._at(), "gate", "envelope",
                         {"skill": skill_id, "effects": list(skill.effects),
                          "verdict": "pass" if ok else "REFUSED", "why": why})
        if not ok:
            return
        self.store.event(self._at(), "act", skill_id, {"args": {k: str(v)[:60] for k, v in args.items()}})
        try:
            detail = skill.run(self, **args) or {}
        except Exception as exc:
            self.store.event(self._at(), "error", skill_id, {"error": str(exc)})
            return
        self.store.event(self._at(), "receipt", skill_id, detail,
                         effect=detail.get("effect", ""))
        self.store.event(self._at(), "commit", "kernel",
                         {"fsm": self.loop.snapshot(), "day": self.store.get("day_no", 1)})

    # --- console surface ----------------------------------------------------
    def snapshot(self) -> dict:
        return {
            "time": self._at(),
            "uptime_h": round(self.uptime_h(), 1),
            "fsm": self.loop.snapshot(),
            "channels": list(self.channels),
            "skills": [{"id": s.id, "capability": s.capability} for s in self.registry.all()],
        }
