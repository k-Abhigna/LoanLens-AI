"""Loan receipts: generator ground truth, Reducto parser (mocked HTTP), eval and export."""

import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "evals"))

import generate_receipts as gen  # noqa: E402
from loanlens.parse import RECEIPT_SCHEMA, parse_all  # noqa: E402


@pytest.fixture
def receipts(tmp_path):
    out = tmp_path / "raw"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_receipts.py"), "--n", "4",
                    "--scans", "1", "--out", str(out)], check=True, capture_output=True)
    return out


def test_emi_formula_matches_known_value():
    # 1,00,000 at 12% for 12 months -> EMI 8,884.88 (standard amortisation)
    assert gen.emi_amount(100_000, 12.0, 12) == pytest.approx(8884.88, abs=0.01)


def test_generated_receipts_add_up(receipts):
    files = sorted(receipts.glob("LR-*.json"))
    assert len(files) == 4 and len(list(receipts.glob("LR-*.jpg"))) == 1
    for f in files:
        loan = json.loads(f.read_text())
        assert (receipts / loan["file"]).exists()
        paid = [s for s in loan["schedule"] if s["status"] != "Due"]
        assert loan["total_paid"] == pytest.approx(sum(s["emi_amount"] for s in paid), abs=0.01)
        assert loan["late_fees"] == pytest.approx(sum(s["late_fee"] for s in paid), abs=0.01)
        for s in loan["schedule"]:
            assert s["principal_component"] + s["interest_component"] == pytest.approx(
                s["emi_amount"], abs=0.011)


def reducto_mock(truth_by_name: dict, calls: list):
    """A fake Reducto server behind the real SDK, so the real request payloads are checked."""
    from reducto import Reducto

    uploaded = {}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/upload"):
            name = next(n for n in truth_by_name if n.encode() in request.content)
            uploaded["id"] = f"reducto://{name}"
            return httpx.Response(200, json={"file_id": uploaded["id"]})
        body = json.loads(request.content)
        assert body["input"] == uploaded["id"]
        assert body["instructions"]["schema"] == RECEIPT_SCHEMA
        truth = truth_by_name[body["input"].removeprefix("reducto://")]
        return httpx.Response(200, json={"response_type": "extract", "job_id": "job-1",
                                         "result": [truth], "usage": {"num_pages": 1}})

    return Reducto(api_key="test", base_url="https://reducto.test",
                   http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_parse_saves_results_and_never_parses_twice(receipts, tmp_path):
    truth = {}
    for f in receipts.glob("LR-*.json"):
        loan = json.loads(f.read_text())
        truth[loan["file"]] = loan
    calls = []
    client = reducto_mock(truth, calls)
    out = tmp_path / "parsed"

    first = parse_all(receipts, out, client=client)
    assert first["parsed"] == 4 and first["failed"] == 0
    saved = json.loads((out / "LR-001.json").read_text())
    assert saved["fields"]["loan_id"] == json.loads((receipts / "LR-001.json").read_text())["loan_id"]
    assert saved["job_id"] == "job-1"

    n_calls = len(calls)
    second = parse_all(receipts, out, client=client)
    assert second == {"parsed": 0, "cached": 4, "failed": 0, "would_parse": 0}
    assert len(calls) == n_calls  # cache hit: no API credits spent

    from run_parse_eval import evaluate
    result = evaluate(receipts, out)
    assert result["field_accuracy"] == 1.0 and result["emi_cell_accuracy"] == 1.0


def test_dry_run_calls_nothing(receipts, tmp_path):
    stats = parse_all(receipts, tmp_path / "parsed", dry_run=True, client=object())
    assert stats["would_parse"] == 4
    assert not list((tmp_path / "parsed").glob("*.json"))
