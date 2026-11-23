"""Ask questions about a loan application file and get cited answers.

Retrieval-augmented generation (RAG) over the applicant's own documents, the facts the
underwriting pipeline extracted from them, and the credit policy. Every chunk carries
metadata (application_id, doc_type, kind), and retrieval is always filtered to one
application, so an answer can never quote another applicant's documents.
"""

from loanlens.rag.assistant import LoanKnowledgeBase

__all__ = ["LoanKnowledgeBase"]
