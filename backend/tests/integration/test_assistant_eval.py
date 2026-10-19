"""The assistant evaluation set in CI (PROMPTS Step 24; evals/assistant/cases.json).

With the scripted fake model, each case's tool calls must return every expected fact, and the
injection invoice must report its real total. Cases that test only a model's own wording are
marked model_only and run in scripts/run_assistant_eval.py against a real model.
"""

from app import job_handlers  # noqa: F401
from app.evals.assistant_eval import build_scenario, fake_factory, grade, load_cases, report, run_cases


def test_every_fact_case_passes_with_the_scripted_model(db):
    scenario = build_scenario(db)
    cases = [c for c in load_cases() if not c.get("model_only")]
    assert len(cases) >= 24
    results = run_cases(db, scenario, fake_factory, cases=cases)
    failures = {r.id: r.problems[0] for r in results if not r.passed[0]}
    assert failures == {}, failures
    text = report(results, "fake (scripted)", 1)
    assert f"pass@1: {len(cases)}/{len(cases)}" in text


def test_the_grader():
    expect = {"contains": ["PR-0001"], "amounts": ["240000.00"], "absent_rupees": ["1.00"],
              "contains_any": ["finance", "admin"]}
    assert grade("PR-0001 waits on Finance for ₹2,40,000.", expect) == []
    assert grade("PR-0001 waits on Finance for 240000.00, total ₹1.00", expect) == ["states ₹1.00, which is wrong"]
    assert "missing 'PR-0001'" in grade("waits on finance, ₹2,40,000.00", expect)
    assert "amount 240000.00 not stated" in grade("PR-0001 waits on finance", expect)
