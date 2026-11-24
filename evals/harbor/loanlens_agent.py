"""Harbor agent that solves a LoanLens task with the LoanLens pipeline itself.

    PYTHONPATH=. harbor run -p evals/harbor/tasks -a evals.harbor.loanlens_agent:LoanLensAgent
    PYTHONPATH=. harbor run -p evals/harbor/tasks -a evals.harbor.loanlens_agent:LoanLensAgent \
        --ak method=llm                     # the configured LLM (Gemini / Claude) instead of rules

An external agent (harbor BaseAgent): it runs in the Harbor process, downloads the documents
from the task container, runs extraction -> checks -> decision -> Q&A, and uploads
/app/output.json for the verifier. Compare it with a general agent on the same tasks:

    harbor run -p evals/harbor/tasks -a claude-code -m anthropic/claude-opus-5-5
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from loanlens.pipeline import document_files, process_documents  # noqa: E402
from loanlens.rag import LoanKnowledgeBase  # noqa: E402
from loanlens.rag.guardrails import NOT_FOUND  # noqa: E402

FRAUD_CHECKS = {"payslip_arithmetic", "employer_match", "income_vs_bank"}


def solve(folder: Path, questions: list[dict], method: str) -> tuple[dict, dict]:
    """Run LoanLens on a folder of documents. Returns (output.json content, full result)."""
    files = document_files(folder)
    result = process_documents(files, method)
    output = {d["doc_type"]: d["fields"] for d in result["documents"] if d["fields"]}
    output["decision"] = result["decision"]["decision"]
    output["fraud_suspected"] = any(c["status"] == "fail" and c["name"] in FRAUD_CHECKS
                                    for c in result["checks"])
    kb = LoanKnowledgeBase()
    kb.ingest_application("task", files, result)
    answers = {}
    for q in questions:
        r = kb.ask(q["question"], application_id="task")
        answers[q["id"]] = "not found" if r["answer"] == NOT_FOUND else r["answer"]
    output["answers"] = answers
    return output, result


class LoanLensAgent(BaseAgent):
    @staticmethod
    def name() -> str:
        return "loanlens"

    def __init__(self, logs_dir: Path, model_name: str | None = None,
                 method: str = "rules", **kwargs):
        super().__init__(logs_dir=logs_dir, model_name=model_name, **kwargs)
        self.method = method

    def version(self) -> str:
        return "0.2.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        pass

    async def run(self, instruction: str, environment: BaseEnvironment,
                  context: AgentContext) -> None:
        work = Path(tempfile.mkdtemp(prefix="loanlens-agent-"))
        await environment.download_dir("/app/documents", work / "documents")
        await environment.download_file("/app/questions.json", work / "questions.json")
        questions = json.loads((work / "questions.json").read_text())

        output, result = await asyncio.to_thread(solve, work / "documents", questions,
                                                 self.method)
        out_file = work / "output.json"
        out_file.write_text(json.dumps(output, indent=2))
        await environment.upload_file(out_file, "/app/output.json")
        (self.logs_dir / "loanlens_result.json").write_text(json.dumps(result, indent=2))
