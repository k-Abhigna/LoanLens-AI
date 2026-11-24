import json

import pytest

from loanlens import harness
from loanlens.extract.grounding import ground
from loanlens.harness import LLMResult, LLMUnavailable
from loanlens.pipeline import process_folder
from loanlens.schemas import PayslipFields


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    for var in ("LLM_PROVIDER", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "LOANLENS_TRACE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(harness, "TRACE_LOG", tmp_path / "traces.jsonl")


def test_one_provider_for_the_whole_app(monkeypatch):
    assert harness.provider_name() is None                      # offline
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert harness.provider_name() == "anthropic"
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    assert harness.provider_name() == "gemini"                  # free tier preferred
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    assert harness.provider_name() == "anthropic"               # explicit choice wins
    monkeypatch.setenv("LLM_PROVIDER", "none")
    assert harness.provider_name() is None


def test_no_provider_raises_one_error_type():
    with pytest.raises(LLMUnavailable):
        harness.complete("qa", "hello")


def test_calls_are_traced_without_prompt_text(monkeypatch):
    monkeypatch.setitem(harness._CALLS, "gemini", lambda p, s, j, m: "answer")
    result = harness.complete("qa", "SECRET applicant text", provider="gemini")
    assert result.text == "answer"
    entry = json.loads(harness.TRACE_LOG.read_text())
    assert entry["task"] == "qa" and entry["ok"] and entry["prompt_version"] == "qa-v1"
    assert "SECRET" not in harness.TRACE_LOG.read_text()
    assert harness.trace_summary()[0]["calls"] == 1


def test_provider_errors_become_llm_unavailable_and_are_traced(monkeypatch):
    def boom(*a):
        raise ConnectionError("down")
    monkeypatch.setitem(harness._CALLS, "anthropic", boom)
    with pytest.raises(LLMUnavailable):
        harness.complete("extract", "x", provider="anthropic")
    assert json.loads(harness.TRACE_LOG.read_text())["ok"] is False


def test_grounding_drops_values_not_in_the_document():
    text = "Employee Name: Maria Diaz\nGross Pay: $9,208.33\nNet Pay: $6,664.44"
    fields = PayslipFields(employee_name="Maria Diaz", gross_pay=9208.33, net_pay=7500.00,
                           employer="Invented Corp")
    clean, removed = ground(fields, text)
    assert clean.gross_pay == 9208.33 and clean.employee_name == "Maria Diaz"
    assert clean.net_pay is None and clean.employer is None
    assert set(removed) == {"net_pay", "employer"}


def test_hallucinated_income_goes_to_review_not_approval(make_docs, monkeypatch):
    """An LLM that invents a higher net pay must not be able to push a case to APPROVE."""
    case, folder = make_docs()
    truth = {k: v for k, v in case.items() if k in ("application", "payslip", "bank_statement")}

    def fake_llm(task, prompt, system=None, json_mode=False, provider=None):
        doc = next(d for d in ("bank statement", "application", "payslip")
                   if f"Extract fields from this {d}" in prompt).replace(" ", "_")
        fields = dict(truth[doc])
        if doc == "payslip":
            fields["net_pay"] = round(fields["net_pay"] * 1.5, 2)   # invented
        return LLMResult(json.dumps(fields), "gemini", "fake", 1.0)

    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setattr("loanlens.extract.llm.complete", fake_llm)
    result = process_folder(folder, "llm")
    slip = next(d for d in result["documents"] if d["doc_type"] == "payslip")
    assert "net_pay" in slip["ungrounded_fields"] and slip["fields"]["net_pay"] is None
    assert result["method"] == "gemini"
    assert result["decision"]["decision"] == "REVIEW"
