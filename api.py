"""REST API: underwrite an application, then ask questions about it.

    uvicorn api:app --reload        ->  http://127.0.0.1:8000/docs

    POST /applications                     upload documents -> decision (+ indexed for Q&A)
    POST /applications/{id}/ask            {"question": "...", "k": 4, "doc_types": [...]}
    GET  /applications                     ids that can be asked about
    GET  /health
"""

from __future__ import annotations

import sys
import tempfile
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from loanlens.config import GENERATED_DIR  # noqa: E402
from loanlens.extract.text import IMAGE_EXTS  # noqa: E402
from loanlens.pipeline import document_files, process_documents, process_folder  # noqa: E402
from loanlens.rag import LoanKnowledgeBase  # noqa: E402
from loanlens.rag.assistant import DOC_TYPES  # noqa: E402
from loanlens.rag.llm import pick_provider  # noqa: E402

app = FastAPI(title="LoanLens AI", version="0.2.0",
              description="Document intelligence for loan underwriting, with cited Q&A.")
kb = LoanKnowledgeBase()
ALLOWED = {".pdf"} | IMAGE_EXTS
MAX_FILE_BYTES = 10 * 1024 * 1024


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    k: int = Field(4, ge=1, le=10)
    doc_types: list[str] | None = Field(None, description=f"Any of {DOC_TYPES}")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "answer_provider": pick_provider(),
            "applications_indexed": len(kb.applications())}


@app.get("/applications")
def applications() -> dict:
    return {"applications": kb.applications()}


@app.post("/applications")
async def underwrite(files: list[UploadFile] = File(...),
                     method: Literal["rules", "llm"] = "rules") -> dict:
    """Run the underwriting pipeline on uploaded documents and index them for Q&A."""
    folder = Path(tempfile.mkdtemp(prefix="loanlens-"))
    for up in files:
        name = Path(up.filename or "").name
        if Path(name).suffix.lower() not in ALLOWED:
            raise HTTPException(415, f"{name}: use PDF or an image ({sorted(ALLOWED)})")
        data = await up.read()
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(413, f"{name} is larger than 10 MB")
        (folder / name).write_bytes(data)
    paths = document_files(folder)
    result = process_documents(paths, method)
    app_id = f"upload-{uuid.uuid4().hex[:8]}"
    kb.ingest_application(app_id, paths, result)
    return {"application_id": app_id, **result}


@app.post("/applications/sample/{application_id}")
def underwrite_sample(application_id: str, method: Literal["rules", "llm"] = "rules") -> dict:
    """Underwrite one of the generated sample applications (see README quick start)."""
    folder = GENERATED_DIR / Path(application_id).name
    if not folder.is_dir():
        raise HTTPException(404, f"No generated application {application_id}")
    result = process_folder(folder, method)
    kb.ingest_application(application_id, document_files(folder), result)
    return result


@app.post("/applications/{application_id}/ask")
def ask(application_id: str, body: AskRequest) -> dict:
    if application_id not in kb.applications():
        raise HTTPException(404, "Unknown application: underwrite it first")
    bad = set(body.doc_types or []) - set(DOC_TYPES)
    if bad:
        raise HTTPException(422, f"Unknown doc_types {sorted(bad)}; use {DOC_TYPES}")
    return kb.ask(body.question, application_id=application_id, k=body.k,
                  doc_types=body.doc_types)
