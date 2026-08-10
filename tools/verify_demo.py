#!/usr/bin/env python3
"""verify_demo — every claim the demo makes, checked against a live instance.

"Everything needs assurance, everything needs verification." Each check states
what a judge should SEE, then proves it from the event log / API rather than from
the fact that a request returned 200. A check that cannot be proven is reported
UNPROVEN, never assumed.

  python3 tools/verify_demo.py --base http://127.0.0.1:8911 --db runtime/anan.db
"""
from __future__ import annotations
import argparse, json, sqlite3, sys, time, urllib.request

R = []          # results
def rec(area, claim, ok, evidence, judge_sees=""):
    R.append({"area": area, "claim": claim,
              "verdict": "PASS" if ok is True else ("FAIL" if ok is False else "UNPROVEN"),
              "evidence": str(evidence)[:200], "judge_sees": judge_sees})


def post(base, path, body=None, timeout=30):
    req = urllib.request.Request(base + path,
                                 data=json.dumps(body or {}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as f:
        return json.loads(f.read() or "{}")


def get(base, path, timeout=30):
    with urllib.request.urlopen(base + path, timeout=timeout) as f:
        return json.loads(f.read() or "{}")


def events(db, kinds=None, since_id=0):
    c = sqlite3.connect(db)
    rows = c.execute("select rowid,at,kind,source,coalesce(detail,''),coalesce(effect,'') "
                     "from events where rowid > ? order by rowid", (since_id,)).fetchall()
    if kinds:
        rows = [r for r in rows if r[2] in kinds]
    return rows


def last_id(db):
    c = sqlite3.connect(db)
    r = c.execute("select coalesce(max(rowid),0) from events").fetchone()
    return r[0]


def wait_for(db, since, pred, seconds):
    """Wait up to `seconds` for an event satisfying pred. Returns (found, waited)."""
    t0 = time.time()
    while time.time() - t0 < seconds:
        for row in events(db, since_id=since):
            if pred(row):
                return row, round(time.time() - t0, 1)
        time.sleep(1.0)
    return None, round(time.time() - t0, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8911")
    ap.add_argument("--db", required=True)
    ap.add_argument("--budget", type=float, default=25.0,
                    help="seconds a judge will plausibly wait for an act to show something")
    a = ap.parse_args()
    B, DB, BUDGET = a.base, a.db, a.budget

    # ---------- 0. the instance itself
    try:
        h = get(B, "/healthz")
        caps = h.get("capabilities", {})
        rec("boot", "server is up and reports a capability receipt", True,
            f"fsm={h.get('fsm')} caps={caps}", "the header shows live + uptime")
    except Exception as exc:
        rec("boot", "server is up", False, exc); return report()

    post(B, "/reset"); time.sleep(2)

    # ---------- 1. every act must SHOW something inside a judge's patience
    ACTS = ["morning", "silence_1", "silence_2", "escalation_timeout",
            "recover", "evening", "insight", "wander", "come_home"]
    for name in ACTS:
        since = last_id(DB)
        t0 = time.time()
        try:
            post(B, "/inject/scenario", {"name": name}, timeout=40)
        except Exception as exc:
            rec("acts", f"act '{name}' accepted", False, exc); continue
        row, waited = wait_for(
            DB, since,
            lambda r: r[2] in ("receipt", "transition") and "inject" not in r[3],
            BUDGET)
        if row:
            rec("acts", f"act '{name}' produces a visible receipt/transition", True,
                f"{row[2]} {row[3]} after {waited}s: {(row[5] or row[4])[:70]}",
                "a new row in the decision log / a state chip lights")
        else:
            rec("acts", f"act '{name}' produces a visible receipt/transition", False,
                f"nothing in {waited}s (judge patience {BUDGET}s)",
                "NOTHING — the judge sees a dead console")

    # ---------- 2. health checks → analysis → guardian
    for kind, score, expect_alert in (("face_symmetry_score", 88, False),
                                      ("face_symmetry_score", 41, True),
                                      ("heart_rate", 142, True)):
        since = last_id(DB)
        try:
            res = post(B, "/api/score",
                       {"telegram_id": "elder", "game_type": kind,
                        "score": score, "metrics": {}}, timeout=40)
        except Exception as exc:
            rec("health", f"{kind}={score} accepted", False, exc); continue
        band = res.get("band", {})
        rec("health", f"{kind}={score} returns an instant plain-language reading",
            bool(band.get("zh")), f"band={band.get('en')} ok={band.get('ok')}",
            "score + what it means, immediately on the result screen")
        # AnAn's own words
        try:
            an = get(B, f"/api/score/analysis?mark={res.get('mark',0)}", timeout=40)
            rec("health", f"{kind}={score} produces AnAn's composed analysis",
                bool(an.get("analysis")), (an.get("analysis") or "")[:90],
                "安安说 block fills in on the result screen")
        except Exception as exc:
            rec("health", f"{kind}={score} analysis", None, exc)
        # guardian fanout on anomaly
        row, waited = wait_for(DB, since,
                               lambda r: r[2] == "receipt" and "health_scan" in r[3], 40)
        if row:
            relayed = "relayed" in (row[5] or "")
            rec("health", f"{kind}={score} → guardian told only when anomalous",
                relayed == expect_alert,
                f"effect={(row[5] or '')[:70]} (expected alert={expect_alert})",
                "a Telegram card appears in the mirror pane" if expect_alert
                else "elder-only encouragement, family not disturbed")
        else:
            rec("health", f"{kind}={score} → health_scan ran", False, f"no receipt in {waited}s")

    # ---------- 3. does anything actually reach Telegram?
    try:
        h = get(B, "/healthz")
        tg = h.get("capabilities", {}).get("telegram")
        rows = events(DB, kinds=("receipt",))
        fam = [r for r in rows if "family" in (r[5] or "") or "relayed" in (r[5] or "")]
        if tg:
            rec("telegram", "family messages actually delivered to Telegram",
                bool(fam), f"telegram_capable={tg}, {len(fam)} family-directed receipts",
                "the guardian's phone buzzes; the mirror pane shows the same card")
        else:
            rec("telegram", "family messages actually delivered to Telegram", None,
                "this instance has telegram disabled (ANAN_DISABLE_TG) — mirror only",
                "mirror pane only; a judge cannot tell delivery from mirroring")
    except Exception as exc:
        rec("telegram", "telegram capability", None, exc)

    # ---------- 4. the bird: does a state change actually reach the mascot?
    try:
        st = get(B, "/state") if False else None
    except Exception:
        st = None
    try:
        h = get(B, "/healthz")
        rec("mascot", "kernel exposes the state the bird animates from",
            bool(h.get("fsm")), f"fsm={h.get('fsm')}",
            "the bird in the header changes pose with the state")
    except Exception as exc:
        rec("mascot", "kernel exposes fsm", False, exc)

    # ---------- 5. receipts exist for every action (the core claim)
    rows = events(DB)
    kinds = [r[2] for r in rows]
    for phase in ("wake", "think", "revalidate", "gate", "act", "receipt", "commit"):
        rec("receipts", f"phase '{phase}' is recorded", phase in kinds,
            f"{kinds.count(phase)} rows", "visible in the decision log")

    report()


def report():
    fails = [r for r in R if r["verdict"] == "FAIL"]
    unp = [r for r in R if r["verdict"] == "UNPROVEN"]
    print(json.dumps({"total": len(R), "pass": len(R) - len(fails) - len(unp),
                      "fail": len(fails), "unproven": len(unp), "checks": R},
                     ensure_ascii=False, indent=1))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
