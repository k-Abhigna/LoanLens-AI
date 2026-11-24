# Harbor results

12 tasks (`evals/harbor/tasks`, demo applications DEMO0001–0012: 5 with injected fraud,
scanned payslips and unseen layouts included). Harbor 0.27, local Docker, 4 concurrent trials.

| Agent | Reward | Field accuracy | Decision correct | Fraud correct | Q&A accuracy | Errors |
|---|---|---|---|---|---|---|
| `oracle` (answer key) | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0 |
| `LoanLensAgent`, rules extractor, offline answers | 0.867 | 0.848 | 0.750 | 0.917 | 0.972 | 0 |

The oracle run proves every task is solvable and the grader is consistent. The LoanLens
rules baseline loses points on payslips and bank statements in the layout its regex rules
have never seen (DEMO0001, 0003, 0006, 0010, 0012): fields it can't read become `null`, so
clean applications go to REVIEW instead of APPROVE (missing is never treated as fraud), and
one clean application with misread fields was flagged as fraud.

Not run yet (needs an API key): `--ak method=llm` (LoanLens with Gemini / Claude) and a
general-purpose agent such as `-a claude-code -m anthropic/claude-opus-5-5`.

Reproduce:

```bash
pip install -r evals/harbor/requirements.txt
python evals/harbor/build_tasks.py --limit 12
harbor run -p evals/harbor/tasks -a oracle -n 4
PYTHONPATH=. harbor run -p evals/harbor/tasks -a evals.harbor.loanlens_agent:LoanLensAgent --ak method=rules -n 4
```
