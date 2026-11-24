"""Generate synthetic loan repayment receipts (PDF) with EMI tables + paired ground truth.

    python scripts/generate_receipts.py              # 18 receipts -> data/raw/receipts/
    python scripts/generate_receipts.py --n 20 --seed 7

Each receipt is a lender's repayment statement for one loan: borrower and loan details
(loan ID, loan type, principal, interest rate, tenure, EMI), an EMI schedule table
(installment, due date, paid date, EMI, principal, interest, late fee, balance, status)
and a payment summary. Next to every receipt is a JSON file with the exact values printed
on it, so a parser (Reducto, or our own) can be scored field by field.

Realism / stress tests built in:
  - 3 lenders with 3 different layouts (labels, column order, date formats differ)
  - 7 loan types, amounts and rates in typical Indian retail ranges (INR)
  - all 7 loan types; a third of loans have 1-3 late payments with late fees
  - 2 receipts are "phone scans" (JPG: tilt, blur, noise) instead of clean PDFs
  - long schedules run onto a second page (tables split across pages)
All names, lenders and loan IDs are fictional.
"""

import argparse
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loanlens.generate.scan import pdf_to_scan  # noqa: E402

OUT_DIR = ROOT / "data" / "raw" / "receipts"

LOAN_TYPES = {  # type: (principal range INR, annual rate range %, tenure options in months)
    "Home Loan": ((1_500_000, 7_500_000), (8.25, 9.75), [120, 180, 240]),
    "Personal Loan": ((50_000, 1_000_000), (10.5, 18.0), [12, 24, 36, 48]),
    "Car Loan": ((300_000, 1_500_000), (8.75, 11.0), [36, 48, 60]),
    "Education Loan": ((200_000, 2_000_000), (8.5, 12.5), [60, 84, 120]),
    "Gold Loan": ((25_000, 400_000), (9.0, 14.0), [6, 12, 24]),
    "Two-Wheeler Loan": ((40_000, 200_000), (9.5, 16.0), [12, 24, 36]),
    "Business Loan": ((300_000, 3_000_000), (12.0, 19.0), [24, 36, 60]),
}
LENDERS = [
    {"name": "Northstar Finance Ltd", "prefix": "NSF", "layout": "A", "color": "#1f3a5f",
     "date_fmt": "%d-%m-%Y"},
    {"name": "Meridian Bank", "prefix": "MRB", "layout": "B", "color": "#0f5e4a",
     "date_fmt": "%d %b %Y"},
    {"name": "Coastal Credit Co-operative", "prefix": "CCC", "layout": "C", "color": "#6b2d5c",
     "date_fmt": "%Y-%m-%d"},
]
FIRST = ["Aarav", "Diya", "Rohan", "Ananya", "Vikram", "Meera", "Karthik", "Sneha", "Arjun",
         "Priya", "Rahul", "Kavya", "Siddharth", "Ishita", "Nikhil", "Pooja", "Varun", "Lakshmi"]
LAST = ["Sharma", "Reddy", "Iyer", "Patel", "Nair", "Gupta", "Rao", "Menon", "Joshi", "Kulkarni",
        "Bose", "Verma", "Pillai", "Desai"]
CITIES = ["Hyderabad", "Bengaluru", "Chennai", "Pune", "Mumbai", "Kochi", "Vijayawada", "Delhi"]


def r2(x: float) -> float:
    return round(x + 1e-9, 2)


def emi_amount(principal: float, annual_rate: float, months: int) -> float:
    """Standard reducing-balance EMI: P * r * (1+r)^n / ((1+r)^n - 1)."""
    r = annual_rate / 12 / 100
    return r2(principal * r * (1 + r) ** months / ((1 + r) ** months - 1))


def add_months(d: date, n: int) -> date:
    month = d.month - 1 + n
    year, month = d.year + month // 12, month % 12 + 1
    return date(year, month, min(d.day, 28))


def build_loan(i: int, rng: random.Random, loan_type: str, late_prone: bool) -> dict:
    (lo, hi), (rlo, rhi), tenures = LOAN_TYPES[loan_type]
    lender = LENDERS[i % len(LENDERS)]
    principal = float(rng.randrange(lo, hi, 5_000))
    rate = round(rng.uniform(rlo, rhi) * 4) / 4  # quarter-percent steps
    tenure = rng.choice(tenures)
    emi = emi_amount(principal, rate, tenure)
    disbursed = date(2024, 1, 5) + timedelta(days=rng.randrange(0, 420))
    first_due = add_months(disbursed.replace(day=min(disbursed.day, 28)), 1)
    paid_count = min(tenure, rng.randint(4, 16))
    shown_upcoming = min(2, tenure - paid_count)
    late_ks = set(rng.sample(range(1, paid_count + 1), k=min(paid_count, rng.randint(1, 3)))
                  ) if late_prone else set()

    schedule, balance = [], principal
    for k in range(1, paid_count + shown_upcoming + 1):
        interest = r2(balance * rate / 12 / 100)
        principal_part = r2(emi - interest) if k < tenure else r2(balance)
        amount = r2(principal_part + interest)
        balance = r2(max(balance - principal_part, 0.0))
        due = add_months(first_due, k - 1)
        row = {"installment_no": k, "due_date": due.isoformat(), "emi_amount": amount,
               "principal_component": principal_part, "interest_component": interest,
               "outstanding_balance": balance}
        if k <= paid_count:
            late_days = rng.choice([5, 9, 14, 21]) if k in late_ks else 0
            row.update(paid_date=(due + timedelta(days=late_days - rng.randint(0, 2)
                                                  if not late_days else late_days)).isoformat(),
                       late_fee=r2(max(500.0, amount * 0.02)) if late_days else 0.0,
                       status="Paid Late" if late_days else "Paid")
        else:
            row.update(paid_date=None, late_fee=0.0, status="Due")
        schedule.append(row)

    paid = [s for s in schedule if s["status"] != "Due"]
    loan_no = f"{lender['prefix']}/{disbursed.year}/{rng.randint(100000, 999999)}"
    return {
        "receipt_id": f"LR-{i + 1:03d}",
        "lender": lender["name"],
        "layout": lender["layout"],
        "loan_id": loan_no,
        "loan_type": loan_type,
        "borrower_name": f"{rng.choice(FIRST)} {rng.choice(LAST)}",
        "branch": rng.choice(CITIES),
        "principal_amount": principal,
        "interest_rate": rate,
        "tenure_months": tenure,
        "emi_amount": emi,
        "disbursement_date": disbursed.isoformat(),
        "statement_date": (date.fromisoformat(paid[-1]["paid_date"]) + timedelta(days=3)
                           ).isoformat(),
        "installments_paid": len(paid),
        "total_paid": r2(sum(s["emi_amount"] for s in paid)),
        "principal_repaid": r2(sum(s["principal_component"] for s in paid)),
        "interest_paid": r2(sum(s["interest_component"] for s in paid)),
        "late_fees": r2(sum(s["late_fee"] for s in paid)),
        "late_payments": sum(s["status"] == "Paid Late" for s in paid),
        "outstanding_principal": paid[-1]["outstanding_balance"],
        "next_due_date": next((s["due_date"] for s in schedule if s["status"] == "Due"), None),
        "schedule": schedule,
    }


# ------------------------------------------------------------------------------ rendering

def inr(x: float) -> str:
    return f"{x:,.2f}"


def fmt_date(iso: str | None, fmt: str) -> str:
    return date.fromisoformat(iso).strftime(fmt) if iso else "-"


def render(loan: dict, path: Path) -> None:
    lender = next(lend for lend in LENDERS if lend["name"] == loan["lender"])
    color, fmt, layout = colors.HexColor(lender["color"]), lender["date_fmt"], lender["layout"]
    styles = getSampleStyleSheet()
    title = ParagraphStyle("t", parent=styles["Title"], textColor=color, fontSize=17,
                           alignment=0, spaceAfter=2)
    small = ParagraphStyle("s", parent=styles["Normal"], fontSize=8.5, textColor=colors.grey)
    h2 = ParagraphStyle("h", parent=styles["Heading2"], textColor=color, fontSize=11,
                        spaceBefore=8, spaceAfter=4)

    def kv_table(rows, cols=2):
        data = [rows[i:i + cols] for i in range(0, len(rows), cols)]
        cells = [[item for pair in row for item in (f"{pair[0]}", pair[1])] for row in data]
        t = Table(cells, colWidths=[38 * mm, 52 * mm] * cols)
        t.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                               ("FONTSIZE", (0, 0), (-1, -1), 9),
                               *[("FONTNAME", (c, 0), (c, -1), "Helvetica-Bold")
                                 for c in range(0, cols * 2, 2)],
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        return t

    story = []
    titles = {"A": "LOAN REPAYMENT RECEIPT", "B": "EMI Payment Statement",
              "C": "Loan Account Statement & Receipt"}
    story.append(Paragraph(loan["lender"], title))
    story.append(Paragraph(f"{titles[layout]} &nbsp;&middot;&nbsp; Branch: {loan['branch']} "
                           f"&nbsp;&middot;&nbsp; Statement date: "
                           f"{fmt_date(loan['statement_date'], fmt)}", small))
    story.append(Spacer(1, 8))

    # Same facts, different labels per lender (what makes parsing non-trivial)
    labels = {
        "A": ["Loan Account No", "Loan Type", "Borrower Name", "Sanctioned Amount",
              "Rate of Interest (p.a.)", "Tenure", "EMI Amount", "Disbursement Date"],
        "B": ["Loan ID", "Product", "Customer", "Principal", "Interest Rate", "Term",
              "Monthly Instalment", "Disbursed On"],
        "C": ["Account Number", "Facility", "Name of Borrower", "Loan Amount", "ROI",
              "Repayment Period", "Equated Monthly Instalment (EMI)", "Date of Disbursal"],
    }[layout]
    values = [loan["loan_id"], loan["loan_type"], loan["borrower_name"],
              f"INR {inr(loan['principal_amount'])}", f"{loan['interest_rate']:.2f}%",
              f"{loan['tenure_months']} months", f"INR {inr(loan['emi_amount'])}",
              fmt_date(loan["disbursement_date"], fmt)]
    story.append(Paragraph("Loan Details", h2))
    story.append(kv_table(list(zip(labels, values))))

    story.append(Paragraph("Repayment Schedule (EMI Table)", h2))
    headers = {
        "A": ["Inst. No", "Due Date", "Paid On", "EMI (INR)", "Principal", "Interest",
              "Late Fee", "Balance", "Status"],
        "B": ["#", "Due", "Payment Date", "Instalment", "Interest", "Principal", "Penalty",
              "Outstanding", "Status"],
        "C": ["No.", "Due Date", "Amount", "Principal Comp.", "Interest Comp.", "Closing Bal.",
              "Paid Date", "Late Charges", "Remarks"],
    }[layout]
    rows = [headers]
    for s in loan["schedule"]:
        base = {"no": str(s["installment_no"]), "due": fmt_date(s["due_date"], fmt),
                "paid": fmt_date(s["paid_date"], fmt), "emi": inr(s["emi_amount"]),
                "prin": inr(s["principal_component"]), "int": inr(s["interest_component"]),
                "fee": inr(s["late_fee"]), "bal": inr(s["outstanding_balance"]),
                "status": s["status"]}
        order = {"A": ["no", "due", "paid", "emi", "prin", "int", "fee", "bal", "status"],
                 "B": ["no", "due", "paid", "emi", "int", "prin", "fee", "bal", "status"],
                 "C": ["no", "due", "emi", "prin", "int", "bal", "paid", "fee", "status"]}[layout]
        rows.append([base[k] for k in order])
    widths = [12, 21, 21, 21, 20, 19, 17, 25, 18]
    table = Table(rows, colWidths=[w * mm for w in widths], repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("BACKGROUND", (0, 0), (-1, 0), color),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (3, 1), (-2, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#b0b7c3")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f5f8")]),
    ]))
    story.append(table)

    story.append(Paragraph("Payment Summary", h2))
    summary_labels = {
        "A": ["Instalments Paid", "Total Amount Paid", "Principal Repaid", "Interest Paid",
              "Total Late Fees", "Outstanding Principal", "Next Due Date"],
        "B": ["EMIs Received", "Total Received", "Principal Received", "Interest Received",
              "Penalty Charged", "Principal Outstanding", "Next Instalment Due"],
        "C": ["No. of EMIs Paid", "Total Paid to Date", "Principal Paid", "Interest Paid",
              "Late Payment Charges", "Balance Principal", "Next EMI Date"],
    }[layout]
    summary_values = [str(loan["installments_paid"]), f"INR {inr(loan['total_paid'])}",
                      f"INR {inr(loan['principal_repaid'])}", f"INR {inr(loan['interest_paid'])}",
                      f"INR {inr(loan['late_fees'])}",
                      f"INR {inr(loan['outstanding_principal'])}",
                      fmt_date(loan["next_due_date"], fmt)]
    story.append(kv_table(list(zip(summary_labels, summary_values))))
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "This is a computer-generated receipt and does not require a signature. Late payment "
        "charges are levied at 2% of the instalment (minimum INR 500) as per the loan "
        "agreement. Synthetic document for testing - all names and numbers are fictional.",
        small))

    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm,
                      topMargin=12 * mm, bottomMargin=12 * mm,
                      title=f"{loan['lender']} - {loan['receipt_id']}").build(story)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=18)
    ap.add_argument("--scans", type=int, default=2, help="how many become phone-scan JPGs")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    for old in args.out.glob("LR-*"):
        old.unlink()
    scan_ids = set(rng.sample(range(args.n), args.scans))
    late_ids = set(rng.sample(range(args.n), round(args.n / 3)))  # a third pay late sometimes
    types = list(LOAN_TYPES)
    for i in range(args.n):
        loan = build_loan(i, rng, types[(i * 3 + i // len(types)) % len(types)], i in late_ids)
        pdf = args.out / f"{loan['receipt_id']}.pdf"
        render(loan, pdf)
        loan["file"] = pdf.name
        if i in scan_ids:  # first page only, like a phone photo of a printout
            jpg = pdf.with_suffix(".jpg")
            pdf_to_scan(pdf, jpg, seed=i)
            pdf.unlink()
            loan["file"] = jpg.name
        (args.out / f"{loan['receipt_id']}.json").write_text(json.dumps(loan, indent=2))
        print(f"{loan['file']:12} {loan['lender']:28} {loan['loan_type']:17} "
              f"INR {loan['principal_amount']:>12,.0f}  late fees {loan['late_fees']:>8,.2f}")
    print(f"\n{args.n} receipts + ground truth JSON in {args.out}")


if __name__ == "__main__":
    main()
