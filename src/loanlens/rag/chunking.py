"""Turn an application file into searchable chunks, each tagged with metadata.

Three kinds of chunk:
  document - raw text of a document (PDF text layer or OCR), split at line boundaries
  fact     - one field the pipeline extracted, a cross-document check, or the decision
  policy   - one rule from the credit policy (shared by every application)

Facts exist because raw OCR text is not always in reading order (a scanned payslip can put
"Net Amount Payable" next to the wrong number). The extracted, validated field is the
reliable version, and the raw text is still there for anything the schema doesn't cover
(individual deductions, bank transactions).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from loanlens.config import POLICY

DOC_LABELS = {
    "application": "Loan application",
    "payslip": "Payslip",
    "bank_statement": "Bank statement",
    "underwriting": "Underwriting result",
    "policy": "Credit policy",
    "unknown": "Unclassified document",
}
# Fields that are counts, not money
NOT_MONEY = {"years_employed", "term_months"}


@dataclass
class Chunk:
    text: str
    source: str                  # file name, or "underwriting" / "credit_policy"
    doc_type: str                # application | payslip | bank_statement | underwriting | policy
    application_id: str | None   # None = shared by every application (the credit policy)
    kind: str = "document"       # document | fact | policy
    section: str | None = None   # nearest heading in the document, or the field / check name
    weak: bool = False           # a fact saying a value could NOT be read: raw text may have it

    def label(self) -> str:
        return DOC_LABELS.get(self.doc_type, self.doc_type)

    def search_text(self) -> str:
        """What the index sees: the document type and heading carry words the body omits."""
        return f"{self.label()} {self.section or ''}\n{self.text}"


_HEADING = re.compile(r"^(section [a-z]\b.*|[A-Z][A-Z &/().-]{3,40})$", re.IGNORECASE)


def _is_heading(line: str) -> bool:
    line = line.strip()
    if not line or any(ch.isdigit() for ch in line) and not line.lower().startswith("section"):
        return False
    return bool(_HEADING.match(line)) and (line.isupper() or line.lower().startswith("section"))


def chunk_document(text: str, max_chars: int = 400, overlap_lines: int = 1
                   ) -> list[tuple[str, str | None]]:
    """Split document text into (chunk, heading) pairs at line boundaries.

    Loan documents are line-oriented (label: value, one transaction per line), so lines are
    never cut in half. Consecutive chunks share `overlap_lines` lines of context.
    """
    chunks: list[tuple[str, str | None]] = []
    buf: list[str] = []
    heading = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _is_heading(line):
            if buf:
                chunks.append(("\n".join(buf), heading))
                buf = []
            heading = line.title() if line.isupper() else line
            continue
        if buf and sum(len(b) + 1 for b in buf) + len(line) > max_chars:
            chunks.append(("\n".join(buf), heading))
            buf = buf[-overlap_lines:] if overlap_lines else []
        buf.append(line)
    if buf:
        chunks.append(("\n".join(buf), heading))
    return chunks


def document_chunks(application_id: str, file: str, doc_type: str, text: str) -> list[Chunk]:
    return [Chunk(text=piece, source=file, doc_type=doc_type, application_id=application_id,
                  kind="document", section=heading)
            for piece, heading in chunk_document(text)]


def _human(name: str) -> str:
    return name.replace("_", " ")


def _format(field: str, value) -> str:
    if value is None:
        return "not found in the document"
    if isinstance(value, list):
        return ", ".join(_format(field, v) for v in value) or "none found"
    if isinstance(value, float) and field not in NOT_MONEY:
        return f"${value:,.2f}"
    return str(value)


def fact_chunks(application_id: str, result: dict) -> list[Chunk]:
    """Extracted fields, check results and the decision as one short chunk each."""
    out: list[Chunk] = []
    method = result.get("method", "rules")
    for doc in result.get("documents", []):
        if not doc.get("fields"):
            continue
        label = DOC_LABELS.get(doc["doc_type"], doc["doc_type"])
        for field, value in doc["fields"].items():
            out.append(Chunk(
                text=f"{label} {_human(field)}: {_format(field, value)} "
                     f"(extracted from {doc['file']} by the {method} extractor, "
                     f"read with {doc['read_with'].replace('_', ' ')})",
                source=doc["file"], doc_type=doc["doc_type"], application_id=application_id,
                kind="fact", section=_human(field), weak=value is None or value == []))

    status_words = {"pass": "passed", "warn": "needs attention", "fail": "failed"}
    for check in result.get("checks", []):
        out.append(Chunk(
            text=f"Cross-document check {_human(check['name'])} {status_words[check['status']]}: "
                 f"{check['detail']}",
            source="underwriting", doc_type="underwriting", application_id=application_id,
            kind="fact", section=_human(check["name"]),
            weak=check["status"] == "warn" and "missing" in check["detail"]))

    decision = result.get("decision")
    if decision:
        out.append(Chunk(
            text=f"AI recommendation for this application: {decision['decision']} (risk score "
                 f"{decision['risk_score']:.0f} out of 100, confidence {decision['confidence']}). "
                 f"Reasons why: " + "; ".join(decision["reasons"]),
            source="underwriting", doc_type="underwriting", application_id=application_id,
            kind="fact", section="decision reasons why"))
        m = decision.get("metrics") or {}
        if not m:
            out.append(Chunk(
                text="Verified monthly income: could not be established, so debt-to-income "
                     "(DTI) and loan-to-income were not calculated.",
                source="underwriting", doc_type="underwriting", application_id=application_id,
                kind="fact", section="affordability metrics"))
        else:
            out.append(Chunk(
                text=f"Verified monthly income: {_format('income', m['verified_monthly_income'])} "
                     f"({m['income_source']}). Existing monthly debt "
                     f"{_format('debt', m['existing_monthly_debt'])}, new loan EMI "
                     f"{_format('emi', m['new_emi'])}. Debt-to-income (DTI) after the loan: "
                     f"{m['dti_after_loan_pct']}%. Loan to annual income: "
                     f"{m['loan_to_income']:.0%}. Years employed: {m['years_employed']}.",
                source="underwriting", doc_type="underwriting", application_id=application_id,
                kind="fact", section="affordability metrics"))
    return out


def policy_chunks() -> list[Chunk]:
    """The credit policy in plain words, generated from config.POLICY so it never drifts."""
    p = POLICY
    rules = {
        "debt-to-income limit": (
            f"Debt-to-income (DTI) is existing monthly debt plus the new loan EMI, divided by "
            f"verified gross monthly income. An application is rejected when DTI after the loan "
            f"is above {p['dti_reject_above']:.0f}%, and sent to human review when it is above "
            f"{p['dti_review_above']:.0f}%."),
        "loan to income limit": (
            f"When the loan amount is more than {p['loan_to_income_review_above']:.0%} of "
            f"verified annual income, the application goes to human review."),
        "minimum employment": (
            f"Applicants employed for less than {p['min_employment_years']} year go to human "
            f"review."),
        "income verification tolerance": (
            f"Income on the payslip, the application and the bank deposits may differ by up to "
            f"{p['income_tolerance']:.0%}. A gap above that needs attention; a gap above "
            f"{p['income_reject_mismatch']:.0%} fails the check and the income is treated as "
            f"not verified."),
        "verified income": (
            "Verified income comes from the payslip only when salary actually deposited in the "
            "bank confirms it. Otherwise income is re-estimated from the bank deposits, because "
            "a payslip is easy to edit and money received is not."),
        "employer match": (
            f"The employer on the application, the payslip letterhead and the payroll deposit "
            f"description must match with at least {p['employer_match_threshold']:.0%} "
            f"similarity."),
        "missing values": (
            "A value that cannot be read from a document is never treated as fraud. The check "
            "is marked as needing attention and the application goes to human review."),
        "human in the loop": (
            "The AI only recommends APPROVE, REVIEW or REJECT. A human loan officer makes the "
            "final decision; overriding the AI requires a written reason, and every decision is "
            "written to the audit log."),
    }
    return [Chunk(text=text, source="credit_policy", doc_type="policy", application_id=None,
                  kind="policy", section=name) for name, text in rules.items()]
