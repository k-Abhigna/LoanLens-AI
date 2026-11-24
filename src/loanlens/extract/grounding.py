"""Output guardrail for LLM extraction: every value must actually be in the document.

An LLM can return a well-formed JSON object with an income the document never states.
Pydantic catches wrong types; this catches invented values. A value that cannot be found
in the document text is set to None, so the cross-document check reports "could not
verify" and the case goes to a human (missing is never treated as fraud).
"""

import re

from pydantic import BaseModel

from loanlens.extract.rules import MONEY, parse_money


def _squash(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", text.lower())  # OCR drops spaces and adds stray dots


def ground(fields: BaseModel, text: str) -> tuple[BaseModel, list[str]]:
    """Return (fields with ungrounded values removed, names of the removed fields)."""
    money = [m for m in (parse_money(x) for x in re.findall(MONEY, text)) if m is not None]
    money = {abs(m) for m in money}
    ints = {int(x) for x in re.findall(r"\d+", text)}
    squashed = _squash(text)

    def found(value) -> bool:
        if isinstance(value, bool) or value is None:
            return True
        if isinstance(value, float):
            return any(abs(abs(value) - m) < 0.006 for m in money)
        if isinstance(value, int):
            return value in ints
        return _squash(str(value)) in squashed

    clean, removed = {}, []
    for name, value in fields.model_dump().items():
        if isinstance(value, list):
            kept = [v for v in value if found(v)]
            if len(kept) != len(value):
                removed.append(name)
            clean[name] = kept
        elif found(value):
            clean[name] = value
        else:
            clean[name] = None
            removed.append(name)
    return type(fields).model_validate(clean), removed
