"""Parse loan receipts with Reducto into structured JSON, cached so credits are spent once.

    pip install reductoai            # in requirements.txt
    set REDUCTO_API_KEY in .env      # key from Reducto Studio

    python -m loanlens.parse --dry-run          # list what would be sent (no API calls)
    python -m loanlens.parse                    # parse data/raw/receipts/* -> data/parsed/
    python -m loanlens.parse --only LR-002      # one receipt
    python -m loanlens.parse --force            # re-parse even if a cached result exists

For every receipt (PDF or scanned JPG) the file is uploaded once, then Reducto's Extract
endpoint returns the fields of RECEIPT_SCHEMA (loan metadata, payment summary and the full
EMI table). The raw API response and the normalized fields are written to
data/parsed/<receipt_id>.json. A receipt that already has a parsed file is skipped, so
re-running never re-spends API credits. Score the results with evals/run_parse_eval.py.

SDK calls used (reductoai 0.27): Reducto().upload(file=...) -> Upload.file_id, then
client.extract.run(input=file_id, instructions={"schema": ..., "system_prompt": ...}).
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from loanlens.config import DATA, ROOT

load_dotenv(ROOT / ".env")

RAW_DIR = DATA / "raw" / "receipts"
PARSED_DIR = DATA / "parsed"
RECEIPT_EXTS = {".pdf", ".jpg", ".jpeg", ".png"}

_MONEY = {"type": "number", "description": "Amount in INR as a plain number, no commas"}
_DATE = {"type": "string", "description": "Date in YYYY-MM-DD format, or null"}

RECEIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "lender": {"type": "string", "description": "Name of the bank or lender"},
        "loan_id": {"type": "string", "description": "Loan / account number exactly as printed"},
        "loan_type": {"type": "string", "description": "Loan product, e.g. Home Loan"},
        "borrower_name": {"type": "string"},
        "principal_amount": {**_MONEY, "description": "Sanctioned / principal loan amount"},
        "interest_rate": {"type": "number", "description": "Annual interest rate in percent"},
        "tenure_months": {"type": "integer", "description": "Loan tenure in months"},
        "emi_amount": {**_MONEY, "description": "Monthly EMI / instalment amount"},
        "disbursement_date": _DATE,
        "statement_date": _DATE,
        "installments_paid": {"type": "integer"},
        "total_paid": {**_MONEY, "description": "Total amount paid / received to date"},
        "principal_repaid": _MONEY,
        "interest_paid": _MONEY,
        "late_fees": {**_MONEY, "description": "Total late fees / penalty / late charges"},
        "outstanding_principal": {**_MONEY, "description": "Outstanding / balance principal"},
        "next_due_date": _DATE,
        "schedule": {
            "type": "array",
            "description": "Every row of the EMI / repayment schedule table",
            "items": {
                "type": "object",
                "properties": {
                    "installment_no": {"type": "integer"},
                    "due_date": _DATE,
                    "paid_date": _DATE,
                    "emi_amount": _MONEY,
                    "principal_component": _MONEY,
                    "interest_component": _MONEY,
                    "late_fee": _MONEY,
                    "outstanding_balance": _MONEY,
                    "status": {"type": "string", "description": "Paid, Paid Late or Due"},
                },
            },
        },
    },
}

SYSTEM_PROMPT = (
    "You extract data from an Indian bank loan repayment receipt / EMI statement. "
    "Different lenders use different labels for the same field (e.g. Sanctioned Amount, "
    "Principal and Loan Amount all mean principal_amount; Penalty and Late Charges mean "
    "late fee). Copy values exactly as printed; amounts as plain numbers without commas or "
    "currency; dates as YYYY-MM-DD. Use null when a value is not on the document. Include "
    "every row of the EMI table, including instalments that are still due."
)


def receipt_files(raw_dir: Path = RAW_DIR) -> list[Path]:
    return sorted(p for p in raw_dir.iterdir() if p.suffix.lower() in RECEIPT_EXTS)


def _first_result(result):
    """Reducto returns the extracted object, or a list with one object per document."""
    if isinstance(result, list):
        return result[0] if result else {}
    return result or {}


def parse_receipt(path: Path, client=None) -> dict:
    """Upload one receipt and extract RECEIPT_SCHEMA. Returns the record saved to disk."""
    if client is None:
        from reducto import Reducto

        client = Reducto()  # reads REDUCTO_API_KEY
    start = time.perf_counter()
    upload = client.upload(file=path)
    response = client.extract.run(
        input=upload.file_id,
        instructions={"schema": RECEIPT_SCHEMA, "system_prompt": SYSTEM_PROMPT},
    )
    raw = response.model_dump() if hasattr(response, "model_dump") else dict(response)
    return {
        "receipt_id": path.stem,
        "source_file": path.name,
        "parser": "reducto",
        "parsed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seconds": round(time.perf_counter() - start, 2),
        "job_id": raw.get("job_id"),
        "usage": raw.get("usage"),
        "fields": _first_result(raw.get("result")),
        "raw_response": raw,
    }


def parse_all(raw_dir: Path = RAW_DIR, out_dir: Path = PARSED_DIR, only: list[str] | None = None,
              force: bool = False, dry_run: bool = False, client=None) -> dict:
    """Parse every receipt that has no cached result yet. Returns counts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = {"parsed": 0, "cached": 0, "failed": 0, "would_parse": 0}
    for path in receipt_files(raw_dir):
        if only and path.stem not in only:
            continue
        target = out_dir / f"{path.stem}.json"
        if target.exists() and not force:
            stats["cached"] += 1
            print(f"cached   {path.name}")
            continue
        if dry_run:
            stats["would_parse"] += 1
            print(f"would parse {path.name}")
            continue
        if client is None:
            if not os.getenv("REDUCTO_API_KEY"):
                raise SystemExit("REDUCTO_API_KEY is not set. Add it to .env, or use --dry-run.")
            from reducto import Reducto

            client = Reducto()
        try:
            record = parse_receipt(path, client)
        except Exception as err:  # keep going: one failed file must not stop the batch
            stats["failed"] += 1
            print(f"FAILED   {path.name}: {type(err).__name__}: {err}"[:200])
            continue
        target.write_text(json.dumps(record, indent=2, default=str))
        stats["parsed"] += 1
        print(f"parsed   {path.name} in {record['seconds']}s -> {target}")
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=Path, default=RAW_DIR)
    ap.add_argument("--out", type=Path, default=PARSED_DIR)
    ap.add_argument("--only", nargs="*", help="receipt ids, e.g. LR-002 LR-007")
    ap.add_argument("--force", action="store_true", help="re-parse cached receipts")
    ap.add_argument("--dry-run", action="store_true", help="list files, call nothing")
    args = ap.parse_args()
    stats = parse_all(args.raw, args.out, args.only, args.force, args.dry_run)
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
