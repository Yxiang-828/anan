"""LLM lanes — agy (Gemini 3.6 Flash) primary, NVIDIA NIM (Nemotron) fallback.

Invocation shapes transplanted from ponytail-agent/brain.py (the working
reference). Every call is one-shot and stateless — continuity lives in the
store, not in a provider session (research/18: no hidden provider-session
continuation). If both lanes fail the caller falls back to templates: the
Hero Loop must never depend on a provider having a good minute.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

AGY_BIN = "/home/dinosaur/.local/bin/agy"
AGY_MODEL = "Gemini 3.6 Flash (High)"
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NVIDIA_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
# Ultra is a REASONING model: it burns tokens thinking before answering, and on
# a slow host that blows the deadline. Super-120b (ponytail's default lane) is
# the fast third rung when ultra times out or rate-limits.
NVIDIA_FALLBACK_MODEL = "nvidia/nemotron-3-super-120b-a12b"
TIMEOUT_S = 90

ROOT = Path(__file__).resolve().parent.parent


class BrainError(Exception):
    pass


def _agy_env() -> dict[str, str]:
    private_home = ROOT / "runtime" / "agy-home"
    private_store = private_home / ".gemini" / "antigravity-cli"
    private_store.mkdir(parents=True, exist_ok=True)
    private_auth = private_store / "antigravity-oauth-token"
    source_auth = Path.home() / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
    if not private_auth.is_file() and source_auth.is_file():
        shutil.copy2(source_auth, private_auth)
        private_auth.chmod(0o600)
    return {
        **os.environ,
        "CI": "true",
        "HOME": str(private_home),
        "XDG_CONFIG_HOME": str(private_home / ".config"),
        "XDG_CACHE_HOME": str(private_home / ".cache"),
        "XDG_STATE_HOME": str(private_home / ".local" / "state"),
    }


def _agy(prompt: str, timeout_s: float = TIMEOUT_S) -> str:
    command = [
        AGY_BIN,
        "--dangerously-skip-permissions",
        "--conversation", str(uuid.uuid4()),
        "--model", AGY_MODEL,
        "--print-timeout", f"{timeout_s}s",
        "--print", prompt,
    ]
    try:
        result = subprocess.run(
            command, cwd=ROOT, env=_agy_env(), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout_s, check=False,
        )
    except FileNotFoundError:
        raise BrainError("agy binary not found") from None
    except subprocess.TimeoutExpired:
        raise BrainError(f"agy timed out after {timeout_s:.1f}s") from None
    answer = result.stdout.strip()
    if result.returncode or not answer or answer.lower().startswith("error:"):
        raise BrainError(f"agy failed (rc={result.returncode}): {answer[:200]}")
    return answer


def _nvidia(prompt: str, system: str, model: str = NVIDIA_MODEL,
            timeout_s: float = TIMEOUT_S, no_think: bool = False) -> str:
    api_key = os.environ.get("NVIDIA_API_KEY", "")
    if not api_key:
        raise BrainError("NVIDIA_API_KEY not set")
    if no_think:
        # Nemotron's documented switch. Measured on the real chooser prompt
        # (junction + 185 chars of FSM state): thinking on 19.1s, off 2.7s —
        # same correct answer. Capping max_tokens instead was worse on both
        # counts: 20.2s AND it truncated mid-reasoning and answered with prose.
        # Only for BOUNDED calls; narration still gets to think.
        system = "detailed thinking off\n" + system
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        # generous: reasoning models spend most of this thinking, not speaking
        "max_tokens": 3000,
        "stream": False,
    }
    request = urllib.request.Request(
        NVIDIA_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise BrainError(f"nvidia HTTP {exc.code}") from None
    except (OSError, ValueError) as exc:
        raise BrainError(f"nvidia request failed ({type(exc).__name__})") from None
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise BrainError("nvidia returned no assistant message") from None
    if not (isinstance(content, str) and content.strip()):
        # reasoning ate the whole budget: an empty answer is a FAILURE, not a reply
        raise BrainError(f"{model}: empty content (reasoning exhausted budget)")
    return content


def think(prompt: str, system: str = "", timeout_s: float | None = None,
          fast_first: bool = False) -> tuple[str, str]:
    """Returns (text, lane). Raises BrainError only if BOTH lanes fail —
    callers catch it and use their template fallback.

    timeout_s bounds THIS call. A junction chooser picking one token from a list
    must not be allowed the same 90s a paragraph gets: it runs on the kernel's
    single tick thread, so a slow answer freezes the whole agent and the operator
    sees a dead console."""
    t = float(timeout_s or TIMEOUT_S)
    full = (system + "\n\n" + prompt).strip() if system else prompt
    sys_msg = system or "You are a helpful assistant."

    # The budget is for the CALL, not for each lane. Bounding only the first lane
    # meant a 6s chooser could still hold the kernel's single tick thread for
    # ~186s (6 + 90 + 90) by failing over twice — the acts-queue-behind-one-slow-
    # call defect, moved rather than fixed. Each lane gets what is left.
    deadline = time.monotonic() + t

    def left(floor: float = 1.5) -> float:
        return max(floor, deadline - time.monotonic())

    # fast_first is for BOUNDED calls — a junction chooser picking one token off a
    # list. agy is a CLI: measured 7.4s for a one-word answer, all of it startup.
    # With a 6s tick-thread budget it can never land, so the chooser fell to the
    # floor every single time and the model was decorative. Nemotron-super over
    # HTTP answers a one-token question in about a second. Order by what the call
    # actually needs, not by which lane is nominally primary.
    if fast_first:
        lanes = [(lambda t: _nvidia(prompt, sys_msg, NVIDIA_FALLBACK_MODEL, timeout_s=t,
                                    no_think=True), "nvidia/nemotron-super"),
                 (lambda t: _agy(full, timeout_s=t), "agy/gemini-3.6-flash")]
    else:
        lanes = [(lambda t: _agy(full, timeout_s=t), "agy/gemini-3.6-flash"),
                 (lambda t: _nvidia(prompt, sys_msg, timeout_s=t), "nvidia/nemotron-ultra"),
                 (lambda t: _nvidia(prompt, sys_msg, NVIDIA_FALLBACK_MODEL, timeout_s=t),
                  "nvidia/nemotron-super")]

    last: BrainError | None = None
    for i, (call, name) in enumerate(lanes):
        if i and time.monotonic() >= deadline:
            break
        try:
            return call(left()), name
        except BrainError as exc:
            last = exc
    raise last or BrainError("no lane answered")
