"""Lightweight AI harness: the ONE place LoanLens talks to an LLM.

Both LLM jobs go through `complete()`:
  extract - turn document text into the validated field schema (extract/llm.py)
  qa      - answer an officer's question from retrieved passages (rag/llm.py)

So the whole app uses ONE model, chosen by configuration:

  LLM_PROVIDER = gemini | anthropic | none     (unset: Gemini if GEMINI_API_KEY is set,
                                                else Claude if ANTHROPIC_API_KEY is set,
                                                else none = offline rules / extractive)
  GEMINI_MODEL    default gemini-flash-latest  (free tier)
  ANTHROPIC_MODEL default claude-opus-5-5

What the harness adds around every call:
  - retries with backoff for rate limits, server errors and timeouts
  - one exception type (LLMUnavailable) so callers can fall back to the offline path
  - a trace line per call in data/llm_traces.jsonl: task, provider, model, prompt version,
    latency, size, success/error. Prompt and document text are NOT logged (applicant PII);
    only a short hash, so repeated prompts can be spotted.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from dotenv import load_dotenv

from loanlens.config import DATA, ROOT

load_dotenv(ROOT / ".env")

TRACE_LOG = DATA / "llm_traces.jsonl"
PROVIDERS = ("gemini", "anthropic")
OFFLINE = {"none", "extractive", "rules", "offline", ""}
# Bump when a prompt changes, so traces and eval results can be compared per version.
PROMPT_VERSIONS = {"extract": "extract-v2", "qa": "qa-v1"}


class LLMUnavailable(RuntimeError):
    """No LLM is configured, or the provider failed after retries."""


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    latency_ms: float


def provider_name() -> str | None:
    """The single configured provider, or None for the offline path."""
    forced = os.getenv("LLM_PROVIDER", "").strip().lower()
    if forced and forced in OFFLINE:
        return None
    if forced:
        if forced in ("claude",):
            return "anthropic"
        if forced not in PROVIDERS:
            raise ValueError(f"LLM_PROVIDER={forced!r}; use one of {PROVIDERS} or 'none'")
        return forced
    if os.getenv("GEMINI_API_KEY"):
        return "gemini"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    return None


def model_name(provider: str) -> str:
    if provider == "gemini":
        return os.getenv("GEMINI_MODEL", "gemini-flash-latest")
    return os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5")


# ---------------------------------------------------------------------------- providers

def _gemini(prompt: str, system: str | None, json_mode: bool, model: str) -> str:
    import requests

    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise LLMUnavailable("GEMINI_API_KEY is not set (add it to .env or Streamlit secrets)")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json" if json_mode else "text/plain",
                             "temperature": 0},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    timeout = float(os.getenv("GEMINI_TIMEOUT", "180"))
    # Free tier: busy servers (timeouts, 429, 5xx) are common, so back off and retry
    for attempt in range(4):
        try:
            resp = requests.post(url, json=body, headers={"x-goog-api-key": key}, timeout=timeout)
        except requests.Timeout:
            if attempt == 3:
                raise LLMUnavailable(f"Gemini did not answer within {timeout:.0f}s ({model})")
        else:
            if resp.ok:
                return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            if resp.status_code not in (429, 500, 503) or attempt == 3:
                raise LLMUnavailable(f"Gemini {resp.status_code} for {model}: {resp.text[:300]}")
        time.sleep(10 * (attempt + 1))
    raise LLMUnavailable("unreachable")


def _anthropic(prompt: str, system: str | None, json_mode: bool, model: str) -> str:
    import anthropic

    if json_mode:
        prompt += "\n\nReturn only the JSON object, with no other text."
    client = anthropic.Anthropic(max_retries=3)  # the SDK retries 429 / 5xx with backoff
    try:
        response = client.beta.messages.create(
            model=model,
            max_tokens=4000,
            system=system or "You are a careful assistant for bank loan underwriting.",
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": "low"},  # extraction and short grounded answers
            # Server-side fallback: if a safety classifier declines, the API retries on a
            # fallback model inside the same call.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.APIError as err:
        raise LLMUnavailable(f"Claude error: {type(err).__name__}: {err}") from err
    if response.stop_reason == "refusal":
        raise LLMUnavailable("Claude declined the request")
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if json_mode and text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    return text


_CALLS = {"gemini": _gemini, "anthropic": _anthropic}


# ---------------------------------------------------------------------------- public API

def complete(task: str, prompt: str, system: str | None = None, json_mode: bool = False,
             provider: str | None = None) -> LLMResult:
    """Run one LLM call for `task` ('extract' or 'qa') on the configured provider."""
    provider = provider or provider_name()
    if provider is None:
        raise LLMUnavailable("No LLM configured (set GEMINI_API_KEY or ANTHROPIC_API_KEY)")
    if provider == "claude":
        provider = "anthropic"
    model = model_name(provider)
    start = time.perf_counter()
    error = None
    try:
        text = _CALLS[provider](prompt, system, json_mode, model)
        return LLMResult(text, provider, model, round((time.perf_counter() - start) * 1000, 1))
    except LLMUnavailable as err:
        error = str(err)[:200]
        raise
    except Exception as err:  # network errors etc.: one exception type for every caller
        error = f"{type(err).__name__}: {err}"[:200]
        raise LLMUnavailable(error) from err
    finally:
        _trace(task, provider, model, prompt, system, start, error)


def _trace(task, provider, model, prompt, system, start, error) -> None:
    if os.getenv("LOANLENS_TRACE", "1") == "0":
        return
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "task": task,
        "prompt_version": PROMPT_VERSIONS.get(task, "unversioned"),
        "provider": provider,
        "model": model,
        "latency_ms": round((time.perf_counter() - start) * 1000, 1),
        "prompt_chars": len(prompt) + len(system or ""),
        "prompt_hash": hashlib.sha256(prompt.encode()).hexdigest()[:12],
        "ok": error is None,
        "error": error,
    }
    try:
        TRACE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with TRACE_LOG.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass  # tracing must never break a request


def trace_summary() -> list[dict]:
    """Calls, error rate and latency per task / provider / model, from the trace log."""
    if not TRACE_LOG.exists():
        return []
    groups: dict[tuple, list[dict]] = {}
    for line in TRACE_LOG.read_text().splitlines():
        if line.strip():
            e = json.loads(line)
            groups.setdefault((e["task"], e["provider"], e["model"], e["prompt_version"]),
                              []).append(e)
    out = []
    for (task, provider, model, version), rows in sorted(groups.items()):
        lat = sorted(r["latency_ms"] for r in rows)
        out.append({"task": task, "provider": provider, "model": model,
                    "prompt_version": version, "calls": len(rows),
                    "error_rate": round(sum(not r["ok"] for r in rows) / len(rows), 3),
                    "p50_ms": lat[len(lat) // 2], "p95_ms": lat[int(len(lat) * 0.95) - 1
                                                                 if len(lat) > 1 else 0]})
    return out
