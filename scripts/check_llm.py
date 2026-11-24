"""Check that the LLM configured in .env works (Gemini or Claude).

    python scripts/check_llm.py

Prints which provider and model the app will use, whether the key is present and
well-formed (without printing the key), then makes one tiny test call.
"""

import os
import sys
from pathlib import Path

# A quick check should fail fast, not wait minutes for a slow or blocked connection.
os.environ.setdefault("GEMINI_TIMEOUT", "20")
print("Checking the LLM setup...", flush=True)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import dotenv_values  # noqa: E402

env_file = ROOT / ".env"
print(f".env file: {env_file} -> {'found' if env_file.exists() else 'NOT FOUND'}")
values = dotenv_values(env_file) if env_file.exists() else {}
for name in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
    key = values.get(name) or ""
    issues = []
    if key and (key != key.strip() or " " in key):
        issues.append("contains spaces")
    if key and key[0] in "\"'":
        issues.append("wrapped in quotes")
    if name == "GEMINI_API_KEY" and key and not key.startswith("AIza"):
        issues.append("does not start with AIza (is this an AI Studio key?)")
    lines = [ln for ln in env_file.read_text(encoding="utf-8", errors="ignore").splitlines()
             if ln.strip().startswith(f"{name}=")] if env_file.exists() else []
    if len(lines) > 1:
        issues.append(f"appears {len(lines)} times in .env (keep one)")
    print(f"{name}: {'set' if key else 'empty'}, length {len(key)}"
          + (f"  PROBLEM: {'; '.join(issues)}" if issues else ""))
    if os.environ.get(name) and os.environ.get(name) != key:
        print(f"  NOTE: a different {name} is set in Windows and wins over .env")

from loanlens.harness import LLMUnavailable, complete, model_name, provider_name  # noqa: E402

provider = provider_name()
if provider is None:
    print("\nNo LLM configured: the app will run offline (rules + extractive answers).")
    sys.exit(1)
print(f"\nProvider: {provider}, model: {model_name(provider)}. Sending a test request "
      f"(gives up after about 20 seconds)...", flush=True)
if provider == "gemini":
    import requests

    key = os.getenv("GEMINI_API_KEY") or values.get("GEMINI_API_KEY") or ""
    model = model_name(provider)
    try:  # one direct call, no retries, so the answer comes back quickly
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": key}, timeout=20,
            json={"contents": [{"parts": [{"text": "Reply with the single word OK"}]}]})
    except requests.RequestException as err:
        print(f"\nFAILED: could not reach Google ({type(err).__name__}). Check your internet, "
              "VPN or office firewall.")
        sys.exit(1)
    if not resp.ok:
        print(f"\nFAILED: Gemini {resp.status_code}: {resp.text[:400]}")
        sys.exit(1)
    text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    print(f"\nSUCCESS: gemini {model} replied {text.strip()!r}")
    sys.exit(0)
try:
    result = complete("qa", "Reply with the single word OK")
except LLMUnavailable as err:
    print(f"\nFAILED: {err}"[:600])
    sys.exit(1)
print(f"\nSUCCESS: {result.provider} {result.model} replied {result.text.strip()!r} "
      f"in {result.latency_ms} ms")
