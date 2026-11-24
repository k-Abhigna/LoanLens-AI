"""Build the Power BI tables for the loan receipts dashboard.

    python scripts/export_powerbi.py                  # parsed values, truth where not parsed
    python scripts/export_powerbi.py --source truth   # ground truth only

Writes data/powerbi/loans.csv (one row per loan; the DAX measures in
docs/powerbi_dax.md use these column names) and data/powerbi/emi_schedule.csv
(one row per EMI instalment, related to Loans on Loan_ID).
"""

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loanlens.parse import PARSED_DIR, RAW_DIR  # noqa: E402

OUT = ROOT / "data" / "powerbi"
LOAN_COLUMNS = {  # Power BI column -> field
    "Loan_ID": "loan_id", "Receipt_ID": "receipt_id", "Lender": "lender",
    "Loan_Type": "loan_type", "Borrower": "borrower_name", "Principal_Amount": "principal_amount",
    "Interest_Rate": "interest_rate", "Tenure_Months": "tenure_months", "EMI_Amount": "emi_amount",
    "Disbursement_Date": "disbursement_date", "Installments_Paid": "installments_paid",
    "Total_Paid": "total_paid", "Principal_Repaid": "principal_repaid",
    "Interest_Paid": "interest_paid", "Late_Fees": "late_fees",
    "Outstanding_Principal": "outstanding_principal", "Next_Due_Date": "next_due_date",
}
SCHEDULE_COLUMNS = {
    "Loan_ID": None, "Installment_No": "installment_no", "Due_Date": "due_date",
    "Paid_Date": "paid_date", "EMI_Amount": "emi_amount", "Principal_Component":
    "principal_component", "Interest_Component": "interest_component", "Late_Fee": "late_fee",
    "Outstanding_Balance": "outstanding_balance", "Status": "status",
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", choices=["parsed", "truth"], default="parsed")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    loans, schedule, used = [], [], {"parsed": 0, "truth": 0}
    for truth_file in sorted(RAW_DIR.glob("LR-*.json")):
        record = json.loads(truth_file.read_text())
        parsed_file = PARSED_DIR / truth_file.name
        if args.source == "parsed" and parsed_file.exists():
            fields = {**json.loads(parsed_file.read_text()).get("fields", {}),
                      "receipt_id": record["receipt_id"]}
            source = "parsed"
        else:
            fields, source = record, "truth"
        used[source] += 1
        loans.append({**{col: fields.get(key) for col, key in LOAN_COLUMNS.items()},
                      "Source": source})
        for row in fields.get("schedule") or []:
            schedule.append({col: (fields.get("loan_id") if key is None else row.get(key))
                             for col, key in SCHEDULE_COLUMNS.items()})
    for name, rows in (("loans.csv", loans), ("emi_schedule.csv", schedule)):
        with (OUT / name).open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print(f"{len(loans)} loans, {len(schedule)} EMI rows -> {OUT} "
          f"(parsed: {used['parsed']}, ground truth: {used['truth']})")


if __name__ == "__main__":
    main()
