"""The application Q&A assistant: ingest -> index -> filtered retrieval -> answer -> guardrails.

    kb = LoanKnowledgeBase()
    kb.ingest_application("APP001", files, underwriting_result)
    kb.ask("What net pay does the payslip show?", application_id="APP001")
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from loanlens.config import DATA
from loanlens.extract.classify import classify
from loanlens.extract.text import get_text
from loanlens.rag.chunking import Chunk, document_chunks, fact_chunks, policy_chunks
from loanlens.rag.guardrails import NOT_FOUND, check_input, check_output
from loanlens.rag.index import TfidfIndex
from loanlens.rag.llm import answer_extractive, generate_answer

DEFAULT_INDEX = DATA / "rag_index.joblib"
DOC_TYPES = ["application", "payslip", "bank_statement", "underwriting", "policy"]


class LoanKnowledgeBase:
    """Chunks for many applications in one index, always queried for ONE application.

    Metadata filtering is what keeps applicants apart: a question about application A only
    ever sees A's chunks plus the shared credit policy, never another applicant's documents.
    """

    def __init__(self, min_score: float = 0.05, min_coverage: float = 0.5) -> None:
        self.min_score = min_score
        self.min_coverage = min_coverage
        self.chunks: list[Chunk] = policy_chunks()
        self.index = TfidfIndex()
        self._lock = threading.Lock()  # Streamlit and FastAPI share one instance across users
        self._dirty = True

    # ------------------------------------------------------------------ building
    def ingest_application(self, application_id: str, files: list[Path],
                           result: dict | None = None) -> int:
        """(Re)load one application's documents and underwriting result. Returns chunk count."""
        new: list[Chunk] = []
        for path in files:
            text, _ = get_text(path)
            doc_type, _ = classify(text)
            new += document_chunks(application_id, Path(path).name, doc_type, text)
        if result:
            new += fact_chunks(application_id, result)
        with self._lock:
            self.chunks = [c for c in self.chunks if c.application_id != application_id] + new
            self._dirty = True
        return len(new)

    def _ensure_index(self) -> None:
        with self._lock:
            if self._dirty:
                self.index = TfidfIndex()
                self.index.build(self.chunks)
                self._dirty = False

    def applications(self) -> list[str]:
        return sorted({c.application_id for c in self.chunks if c.application_id})

    def save(self, path: Path = DEFAULT_INDEX) -> None:
        self._ensure_index()
        self.index.save(path)

    @classmethod
    def load(cls, path: Path = DEFAULT_INDEX, **kwargs) -> "LoanKnowledgeBase":
        kb = cls(**kwargs)
        kb.index = TfidfIndex.load(path)
        kb.chunks = kb.index.chunks
        kb._dirty = False
        return kb

    # ------------------------------------------------------------------ querying
    def retrieve(self, question: str, application_id: str, k: int = 4,
                 doc_types: list[str] | None = None) -> list[tuple[Chunk, float]]:
        """Top-k passages for this application (+ shared policy), or [] if none covers it."""
        self._ensure_index()

        def where(c: Chunk) -> bool:
            in_scope = c.application_id in (application_id, None)
            return in_scope and (not doc_types or c.doc_type in doc_types)

        candidates = self.index.search(question, k=k * 6, min_score=self.min_score, where=where)
        # A fact saying a value could not be read is weak evidence: halve its score.
        candidates = sorted(((c, s * 0.5 if c.weak else s) for c, s in candidates),
                            key=lambda h: -h[1])
        # Two lanes, so neither kind of evidence crowds out the other:
        #   raw document text - holds the value even when extraction failed (k // 2 slots)
        #   facts and policy  - extracted values, checks and the decision for THIS applicant,
        #                       plus at most one shared credit-policy rule
        docs = [h for h in candidates if h[0].kind == "document"][:k // 2]
        policy = [h for h in candidates if h[0].kind == "policy"][:1]
        facts = [h for h in candidates if h[0].kind == "fact"]
        hits = docs + sorted(facts + policy, key=lambda h: -h[1])[:k - len(docs)]
        hits = sorted(hits, key=lambda h: -h[1])
        if not hits or max(self.index.coverage(question, c) for c, _ in hits) < self.min_coverage:
            return []
        return hits

    def ask(self, question: str, application_id: str, k: int = 4,
            doc_types: list[str] | None = None) -> dict:
        start = time.perf_counter()
        base = {"question": question, "application_id": application_id}

        gate = check_input(question)
        if not gate.allowed:
            return {**base, "answer": gate.message, "provider": "guardrail", "blocked": True,
                    "guardrail": gate.reason, "output_flags": [], "sources": [],
                    "latency_ms": round((time.perf_counter() - start) * 1000, 1)}

        hits = self.retrieve(question, application_id, k=k, doc_types=doc_types)
        answer, provider = generate_answer(question, hits, idf=self.index.idf)
        passages = [c.text for c, _ in hits]
        verdict = check_output(answer, passages)
        flags = list(verdict.flags)
        if not verdict.ok and not provider.startswith("extractive"):
            # The LLM cited nothing, cited a passage that doesn't exist, or used a number
            # the passages don't contain: fall back to an answer built only from the passages.
            answer = answer_extractive(question, hits, idf=self.index.idf)
            provider = f"extractive (guardrail replaced {provider} answer)"

        return {
            **base,
            "answer": answer,
            "provider": provider,
            "blocked": False,
            "guardrail": None,
            "output_flags": flags,
            "found": answer != NOT_FOUND,
            "latency_ms": round((time.perf_counter() - start) * 1000, 1),
            "sources": [
                {"n": n, "source": c.source, "doc_type": c.doc_type, "kind": c.kind,
                 "application_id": c.application_id, "section": c.section,
                 "score": round(score, 3), "text": c.text}
                for n, (c, score) in enumerate(hits, start=1)
            ],
        }


def build_portfolio(data_dir: Path, method: str = "rules", limit: int | None = None,
                    kb: LoanKnowledgeBase | None = None) -> tuple[LoanKnowledgeBase, dict]:
    """Underwrite and index every generated application. Returns (kb, results by id)."""
    import pandas as pd

    from loanlens.pipeline import document_files, process_folder

    kb = kb or LoanKnowledgeBase()
    manifest = pd.read_csv(data_dir / "manifest.csv", dtype=str)
    ids = manifest.application_id.tolist()[:limit] if limit else manifest.application_id.tolist()
    results = {}
    for app_id in ids:
        folder = data_dir / app_id
        result = process_folder(folder, method)
        kb.ingest_application(app_id, document_files(folder), result)
        results[app_id] = result
    return kb, results
