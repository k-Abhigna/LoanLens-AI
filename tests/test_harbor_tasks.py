"""The Harbor task suite: building a task, and the verifier's scoring."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals" / "harbor"))
sys.path.insert(0, str(ROOT / "evals" / "harbor" / "template" / "tests"))

from build_tasks import build_task  # noqa: E402
from grade import grade  # noqa: E402


@pytest.fixture
def task(make_docs, tmp_path):
    case, folder = make_docs(fraud="inflated_income")
    case["labels"]["fraud_type"] = "inflated_income"
    (folder / "truth.json").write_text(json.dumps(case))
    return build_task(folder, tmp_path / "tasks")


def test_task_has_harbor_layout(task):
    for path in ("instruction.md", "task.toml", "environment/Dockerfile", "tests/test.sh",
                 "tests/grade.py", "tests/expected.json", "solution/solve.sh",
                 "environment/questions.json"):
        assert (task / path).exists(), path
    assert len(list((task / "environment" / "documents").iterdir())) == 3
    # The answer key is only in tests/ and solution/, never in the agent's environment
    assert "expected" not in (task / "environment" / "questions.json").read_text()


def test_oracle_scores_one_and_garbage_scores_zero(task):
    expected = json.loads((task / "tests" / "expected.json").read_text())
    assert expected["fraud"] is True and expected["decision"] == "REJECT"
    oracle = json.loads((task / "solution" / "expected_output.json").read_text())
    assert grade(oracle, expected)["reward"] == 1.0
    assert grade(None, expected)["reward"] == 0.0
    assert grade({"decision": "APPROVE"}, expected)["reward"] < 0.1  # only null fields match


def test_verifier_script_writes_reward_json(task, tmp_path):
    out = tmp_path / "output.json"
    out.write_text((task / "solution" / "expected_output.json").read_text())
    subprocess.run([sys.executable, str(task / "tests" / "grade.py"), "--output", str(out),
                    "--expected", str(task / "tests" / "expected.json"),
                    "--reward-dir", str(tmp_path / "logs")], check=True, capture_output=True)
    reward = json.loads((tmp_path / "logs" / "reward.json").read_text())
    assert reward["reward"] == 1.0 and all(isinstance(v, (int, float)) for v in reward.values())


def test_loanlens_solves_a_clean_task(make_docs, tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "none")
    pytest.importorskip("harbor")
    sys.path.insert(0, str(ROOT))
    from evals.harbor.loanlens_agent import solve

    case, folder = make_docs()
    (folder / "truth.json").write_text(json.dumps(case))
    task = build_task(folder, tmp_path / "tasks")
    questions = json.loads((task / "environment" / "questions.json").read_text())
    output, _ = solve(task / "environment" / "documents", questions, "rules")
    scores = grade(output, json.loads((task / "tests" / "expected.json").read_text()))
    assert scores["reward"] == 1.0, scores
