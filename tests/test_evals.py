import json
from pathlib import Path

from bot.agent.intent import allowed_tools_for_intent, classify_intent_text


def test_eval_cases_intent_and_allowed_tools():
    cases = [
        json.loads(line)
        for line in Path("tests/evals/cases.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]

    assert cases
    for case in cases:
        intent = classify_intent_text(case["message"])
        assert intent.value == case["expected_intent"], case["id"]
        assert allowed_tools_for_intent(intent) == case["allowed_tools"], case["id"]
