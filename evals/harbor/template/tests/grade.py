"""Harbor verifier for a LoanLens underwriting task. Standard library only.

Scores /app/output.json against the answer key and writes /logs/verifier/reward.json:
  field_accuracy    share of the 25 document fields read correctly
  decision_correct  1 if APPROVE / REVIEW / REJECT matches the policy applied to the true values
  fraud_correct     1 if fraud_suspected matches whether fraud was injected
  qa_accuracy       share of questions answered correctly ("not found" when unanswerable)
  reward            0.4 * fields + 0.2 * decision + 0.2 * fraud + 0.2 * qa
"""

import argparse
import json
from pathlib import Path

WEIGHTS = {"field_accuracy": 0.4, "decision_correct": 0.2, "fraud_correct": 0.2,
           "qa_accuracy": 0.2}
NOT_FOUND_MARKERS = ("not found", "couldn't find", "could not find", "cannot find",
                     "not in the documents", "not stated", "not available")


def same(pred, truth) -> bool:
    """Numbers within 0.1% (min 1 cent); text case- and whitespace-insensitive."""
    if isinstance(truth, list):
        return isinstance(pred, list) and len(pred) == len(truth) and all(
            same(p, t) for p, t in zip(pred, truth))
    if isinstance(truth, (int, float)) and not isinstance(truth, bool):
        try:
            return abs(float(pred) - float(truth)) <= max(0.01, abs(truth) * 0.001)
        except (TypeError, ValueError):
            return False
    if truth is None:
        return pred is None
    return pred is not None and " ".join(str(pred).lower().split()) == " ".join(
        str(truth).lower().split())


def answer_ok(answer, expected: list[str]) -> bool:
    text = str(answer or "").lower()
    if not expected:  # unanswerable from the documents
        return not text.strip() or any(m in text for m in NOT_FOUND_MARKERS)
    squash = text.replace(",", "").replace("$", "")
    return all(e.lower() in text or e.lower().replace(",", "") in squash for e in expected)


def grade(output: dict | None, expected: dict) -> dict:
    if not isinstance(output, dict):
        return {**{k: 0.0 for k in WEIGHTS}, "reward": 0.0, "valid_output": 0}
    hits = total = 0
    for doc, fields in expected["fields"].items():
        got = output.get(doc) if isinstance(output.get(doc), dict) else {}
        for name, truth in fields.items():
            hits += same(got.get(name), truth)
            total += 1
    answers = output.get("answers") if isinstance(output.get("answers"), dict) else {}
    qa = [answer_ok(answers.get(q["id"]), q["expected"]) for q in expected["questions"]]
    scores = {
        "field_accuracy": hits / total,
        "decision_correct": float(str(output.get("decision", "")).upper() == expected["decision"]),
        "fraud_correct": float(output.get("fraud_suspected") is expected["fraud"]),
        "qa_accuracy": sum(qa) / len(qa),
    }
    scores = {k: round(v, 4) for k, v in scores.items()}
    scores["reward"] = round(sum(WEIGHTS[k] * v for k, v in scores.items()), 4)
    scores["valid_output"] = 1
    return scores


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("/app/output.json"))
    ap.add_argument("--expected", type=Path, default=Path("/tests/expected.json"))
    ap.add_argument("--reward-dir", type=Path, default=Path("/logs/verifier"))
    args = ap.parse_args()
    try:
        output = json.loads(args.output.read_text())
    except (OSError, ValueError):
        output = None
    scores = grade(output, json.loads(args.expected.read_text()))
    args.reward_dir.mkdir(parents=True, exist_ok=True)
    (args.reward_dir / "reward.json").write_text(json.dumps(scores, indent=2))
    print(json.dumps(scores, indent=2))


if __name__ == "__main__":
    main()
