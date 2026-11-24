"""Score parsed receipts (data/parsed/) against the generated ground truth (data/raw/receipts/).

    python evals/run_parse_eval.py

Reports field accuracy for the loan details and payment summary, EMI-table accuracy
(rows found, cell accuracy) and a breakdown by lender layout and by PDF vs scan.
Numbers match within 1 paisa (or 0.1%); text is case- and whitespace-insensitive;
loan IDs ignore spaces.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from loanlens.config import RESULTS_DIR  # noqa: E402
from loanlens.parse import PARSED_DIR, RAW_DIR, RECEIPT_SCHEMA  # noqa: E402

FIELDS = [f for f in RECEIPT_SCHEMA["properties"] if f != "schedule"]
ROW_FIELDS = list(RECEIPT_SCHEMA["properties"]["schedule"]["items"]["properties"])


def same(pred, truth) -> bool:
    if truth is None:
        return pred in (None, "", "-")
    if isinstance(truth, (int, float)) and not isinstance(truth, bool):
        try:
            value = float(str(pred).replace(",", "").replace("INR", "").replace("%", "").strip())
        except (TypeError, ValueError):
            return False
        return abs(value - truth) <= max(0.011, abs(truth) * 0.001)
    norm = lambda v: " ".join(str(v).lower().replace(" / ", "/").split())  # noqa: E731
    return pred is not None and norm(pred) == norm(truth)


def evaluate(raw_dir: Path, parsed_dir: Path) -> dict:
    field_hits = defaultdict(lambda: [0, 0])
    group_hits = defaultdict(lambda: [0, 0])
    rows_found = rows_total = cell_hits = cell_total = 0
    evaluated, missing = [], []
    for truth_file in sorted(raw_dir.glob("LR-*.json")):
        truth = json.loads(truth_file.read_text())
        parsed_file = parsed_dir / f"{truth['receipt_id']}.json"
        if not parsed_file.exists():
            missing.append(truth["receipt_id"])
            continue
        got = json.loads(parsed_file.read_text()).get("fields") or {}
        kind = "scan" if truth["file"].endswith(".jpg") else "pdf"
        for f in FIELDS:
            ok = same(got.get(f), truth[f])
            for key in (f, f"layout {truth['layout']}", kind):
                bucket = field_hits if key == f else group_hits
                bucket[key][0] += ok
                bucket[key][1] += 1
        got_rows = {r.get("installment_no"): r for r in got.get("schedule") or []
                    if isinstance(r, dict)}
        for row in truth["schedule"]:
            rows_total += 1
            match = got_rows.get(row["installment_no"])
            rows_found += match is not None
            for f in ROW_FIELDS:
                cell_total += 1
                cell_hits += match is not None and same(match.get(f), row[f])
        evaluated.append(truth["receipt_id"])

    total = sum(v[1] for v in field_hits.values())
    return {
        "receipts_evaluated": len(evaluated),
        "receipts_not_parsed": missing,
        "field_accuracy": round(sum(v[0] for v in field_hits.values()) / total, 3) if total else None,
        "field_accuracy_by_field": {f: round(h / n, 3) for f, (h, n) in field_hits.items()},
        "field_accuracy_by_group": {g: round(h / n, 3) for g, (h, n) in group_hits.items()},
        "emi_rows_found": round(rows_found / rows_total, 3) if rows_total else None,
        "emi_cell_accuracy": round(cell_hits / cell_total, 3) if cell_total else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=RAW_DIR)
    ap.add_argument("--parsed", type=Path, default=PARSED_DIR)
    args = ap.parse_args()
    r = evaluate(args.raw, args.parsed)
    if not r["receipts_evaluated"]:
        raise SystemExit("No parsed receipts found. Run: python -m loanlens.parse")
    lines = ["# Receipt parsing evaluation (Reducto vs ground truth)", "",
             f"Receipts evaluated: **{r['receipts_evaluated']}**"
             + (f" (not parsed yet: {', '.join(r['receipts_not_parsed'])})"
                if r["receipts_not_parsed"] else ""), "",
             "| Metric | Value |", "|---|---|",
             f"| Field accuracy (loan details + summary) | {r['field_accuracy']:.1%} |",
             f"| EMI table rows found | {r['emi_rows_found']:.1%} |",
             f"| EMI table cell accuracy | {r['emi_cell_accuracy']:.1%} |",
             *[f"| Field accuracy, {g} | {v:.1%} |"
               for g, v in sorted(r["field_accuracy_by_group"].items())],
             "", "| Field | Accuracy |", "|---|---|",
             *[f"| {f} | {v:.1%} |" for f, v in sorted(r["field_accuracy_by_field"].items(),
                                                       key=lambda kv: kv[1])]]
    md = "\n".join(lines) + "\n"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "parse_reducto.md").write_text(md)
    (RESULTS_DIR / "parse_reducto.json").write_text(json.dumps(r, indent=2))
    print(md)


if __name__ == "__main__":
    main()
