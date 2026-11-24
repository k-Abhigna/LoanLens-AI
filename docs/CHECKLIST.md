# LoanLens AI: what's done and what's left

Plan = the handwritten "Resume Preparation" notes. ✅ done · ⬜ left for you · 🟡 partly done

## Build

| # | Step | Status | What's left |
|---|---|---|---|
| 1 | Fresh repo: LoanLens + DocQA-RAG | ✅ | `github.com/k-Abhigna/LoanLens-AI` (`main`). Optional: archive the two old repos |
| 2 | Synthetic loan receipts + EMI tables + ground-truth JSON in `data/raw/` | ✅ | 18 receipts in `data/raw/receipts/` |
| 3 | Parse with Reducto, save JSON in `data/parsed/` | 🟡 | Code done and tested with a mocked API. **Run it:** add `REDUCTO_API_KEY` to `.env`, `python -m loanlens.parse`, then `python evals/run_parse_eval.py`, commit `data/parsed/` and put the numbers in the README |
| 4 | Input & output guardrails | ✅ | Q&A input/output, extraction grounding, upload limits |
| 5 | Merge classification + retrieval | 🟡 | Done for application / payslip / bank statement. **Receipts are not in the app yet:** add a `loan_receipt` document type to the classifier and index parsed receipts for Q&A |
| 6 | Lightweight AI harness | ✅ | `src/loanlens/harness.py` |
| 7 | Automated evals | 🟡 | Offline evals + Harbor done. **Run with an LLM:** set `GEMINI_API_KEY`, then `python evals/run_eval.py --method llm --limit 60 --sleep 7`, `python evals/run_rag_eval.py` and Harbor `--ak method=llm`; optionally `-a claude-code` |
| 8 | Clean README: flow diagram, eval table, setup | 🟡 | Add Reducto + LLM numbers, a Power BI screenshot and the live demo link when you have them |
| — | Power BI dashboard (DAX measures) | ⬜ | `python scripts/export_powerbi.py`, load the two CSVs, paste measures from `docs/powerbi_dax.md`, screenshot into `docs/` |
| — | Live demo | ⬜ | Redeploy on Streamlit Cloud from `LoanLens-AI` (`app/streamlit_app.py`), add `GEMINI_API_KEY` in Secrets, put the link in the README |
| — | Local copy | ⬜ | `git clone https://github.com/k-Abhigna/LoanLens-AI.git` into `C:\Job\Resume\My Projects\AI Project` |

## Interview prep (step 9)

| Step | Status |
|---|---|
| 90-second project pitch | ⬜ |
| Top 15 interview Q&A in simple words | ⬜ |
| Record yourself daily until it flows: Why Reducto? Why metadata filtering? How do guardrails and evals work? | ⬜ |
| Resume bullets with real numbers | ⬜ |
