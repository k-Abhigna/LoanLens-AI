"""Input and output guardrails for the application Q&A assistant.

Input  (before retrieval): block empty / oversized questions, prompt-injection attempts,
       requests to make or change a credit decision, and requests for sensitive data.
Output (after generation): every answer must cite a passage that exists, and every number
       in the answer must appear in the passages it cites. An LLM answer that fails is
       replaced by the extractive answer, which is built only from passage text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from loanlens.rag.text import numbers

MAX_QUESTION_CHARS = 500
NOT_FOUND = "I couldn't find that in this application's documents."

_INJECTION = re.compile(
    r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|rules|prompts?)"
    r"|disregard (the |your |all )?(instructions|rules|system)"
    r"|(reveal|print|show|repeat) (me )?(your|the) (system )?(prompt|instructions)"
    r"|system prompt|you are now|act as (a|an) |pretend (to be|you are)|jailbreak"
    r"|developer mode|new instructions:", re.IGNORECASE)

_DECISION = re.compile(
    r"^\s*(please\s+|can you\s+|could you\s+)?(approve|reject|decline|override|overrule|"
    r"change|set|update|mark)\b.*\b(loan|application|decision|recommendation|it|this|them)\b"
    r"|\b(mark|set|change) (it|this|the (loan|application|decision)) (as|to) "
    r"(approved?|rejected?|declined?)", re.IGNORECASE)

_SENSITIVE = re.compile(
    r"\b(ssn|social security number|full account number|routing number|password|pin code"
    r"|card number|cvv)\b", re.IGNORECASE)


@dataclass
class InputCheck:
    allowed: bool
    reason: str | None = None   # machine-readable rule name
    message: str | None = None  # what the officer sees


def check_input(question: str) -> InputCheck:
    q = (question or "").strip()
    if not q:
        return InputCheck(False, "empty", "Please type a question.")
    if len(q) > MAX_QUESTION_CHARS:
        return InputCheck(False, "too_long",
                          f"Questions are limited to {MAX_QUESTION_CHARS} characters.")
    if _INJECTION.search(q):
        return InputCheck(False, "prompt_injection",
                          "This looks like an attempt to change the assistant's instructions, "
                          "so it was not sent.")
    if _DECISION.search(q):
        return InputCheck(False, "decision_request",
                          "The assistant answers questions about the file; it cannot approve, "
                          "reject or change a decision. Use the officer decision form.")
    if _SENSITIVE.search(q):
        return InputCheck(False, "sensitive_data",
                          "The assistant does not return full account numbers, SSNs or other "
                          "credentials.")
    return InputCheck(True)


_CITATION = re.compile(r"\[(\d+)\]")


@dataclass
class OutputCheck:
    ok: bool
    flags: list[str] = field(default_factory=list)


def check_output(answer: str, passages: list[str]) -> OutputCheck:
    """Citations must point at real passages; numbers must come from the cited passages."""
    if answer.strip() == NOT_FOUND:
        return OutputCheck(True)
    flags = []
    cited = [int(n) for n in _CITATION.findall(answer)]
    if not cited:
        flags.append("no_citation")
    if any(n < 1 or n > len(passages) for n in cited):
        flags.append("invalid_citation")

    valid = [passages[n - 1] for n in set(cited) if 1 <= n <= len(passages)]
    grounded = set().union(*(numbers(p) for p in valid)) if valid else set()
    claimed = numbers(_CITATION.sub(" ", answer))
    ungrounded = {x for x in claimed if not any(abs(x - g) < 0.006 for g in grounded)}
    # Percent values may be written as 0.45 or 45 - accept either
    ungrounded = {x for x in ungrounded
                  if not any(abs(x - g * 100) < 0.6 or abs(x * 100 - g) < 0.6 for g in grounded)}
    if ungrounded:
        flags.append("ungrounded_numbers")
    return OutputCheck(not flags, flags)
