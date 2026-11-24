"""End-to-end: documents in -> classified, extracted, checked, decided.

    python -m loanlens.pipeline data/generated/<application_id>
    python -m loanlens.pipeline data/generated/<application_id> --method llm

Methods: "rules" (offline regex baseline) or "llm" (the one model configured in
loanlens/harness.py). "gemini" / "anthropic" force a specific provider.
"""

import argparse
import json
import time
from pathlib import Path

from loanlens.checks import run_checks
from loanlens.decide import decide
from loanlens.extract import rules
from loanlens.extract.classify import classify
from loanlens.extract.text import IMAGE_EXTS, get_text

METHODS = ["rules", "llm", "gemini", "anthropic"]


def extract_fields(doc_type: str, text: str, method: str):
    """Return (fields, ungrounded field names). LLM values not found in the text are dropped."""
    if method == "rules":
        return rules.extract(doc_type, text), []
    from loanlens.extract import llm  # only needed when an LLM is used
    from loanlens.extract.grounding import ground

    fields = llm.extract(doc_type, text, provider=None if method == "llm" else method)
    return ground(fields, text)


def method_label(method: str) -> str:
    """'llm' -> the provider actually configured, e.g. 'gemini', for reports and the UI."""
    if method != "llm":
        return method
    from loanlens.harness import provider_name
    return provider_name() or "llm (none configured)"


def process_documents(paths: list[Path], method: str = "rules") -> dict:
    start = time.perf_counter()
    docs, fields = [], {}
    for path in paths:
        text, read_with = get_text(path)
        doc_type, conf = classify(text)
        entry = {"file": path.name, "read_with": read_with, "doc_type": doc_type,
                 "type_confidence": conf, "fields": None, "ungrounded_fields": []}
        if doc_type != "unknown" and doc_type not in fields:
            extracted, ungrounded = extract_fields(doc_type, text, method)
            entry["ungrounded_fields"] = ungrounded
            if read_with == "ocr" and doc_type == "payslip":
                extracted = rules.clean_ocr_payslip(extracted)
            fields[doc_type] = extracted
            entry["fields"] = extracted.model_dump()
        docs.append(entry)

    app, slip, bank = (fields.get(k) for k in ("application", "payslip", "bank_statement"))
    checks, derived = run_checks(app, slip, bank)
    used_ocr = any(d["read_with"] == "ocr" for d in docs)
    decision = decide(app, checks, derived, used_ocr=used_ocr)
    return {
        "method": method_label(method),
        "documents": docs,
        "checks": [c.model_dump() for c in checks],
        "decision": decision.model_dump(),
        "seconds": round(time.perf_counter() - start, 2),
    }


def document_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir()
                  if p.suffix.lower() == ".pdf" or p.suffix.lower() in IMAGE_EXTS)


def process_folder(folder: Path, method: str = "rules") -> dict:
    result = process_documents(document_files(folder), method)
    result["application_id"] = folder.name
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--method", choices=METHODS, default="rules")
    args = ap.parse_args()
    print(json.dumps(process_folder(args.folder, args.method), indent=2))


if __name__ == "__main__":
    main()
