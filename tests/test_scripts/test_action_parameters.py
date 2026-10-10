"""Offline fixtures: strict input, historical compatibility and error privacy."""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from backend.schemas.action_parameters import CONTRACT, action_parameter_errors
from backend.schemas.dag import VALID_ACTION_TYPES, DAGScript

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads((ROOT / "tests/fixtures/action-parameters.v1.json").read_text(encoding="utf-8"))


def concise(errors):
    return [f"{'.'.join(map(str, error['loc'][3:]))}:{error['type'].split('.')[-1]}" for error in errors]


@pytest.mark.parametrize("action", list(FIXTURES["valid_actions"].values()), ids=FIXTURES["valid_actions"])
def test_all_32_published_actions_have_a_valid_example_without_source_mutation(action):
    original = deepcopy(action)
    assert action_parameter_errors([{"action": action}]) == []
    assert action == original


@pytest.mark.parametrize("case", FIXTURES["cases"], ids=[row["name"] for row in FIXTURES["cases"]])
def test_shared_python_and_typescript_parameter_cases(case):
    original = deepcopy(case["action"])
    errors = action_parameter_errors([{"action": case["action"]}])
    assert concise(errors) == case["errors"]
    assert case["action"] == original
    assert all(set(error) == {"loc", "type", "msg"} for error in errors)
    assert "PRIVATE" not in json.dumps(errors)


def test_contract_covers_exact_published_set_and_generated_copy_matches():
    assert set(CONTRACT["actions"]) == VALID_ACTION_TYPES == set(FIXTURES["valid_actions"])
    assert (ROOT / "frontend/lib/dag/action-contract.v1.json").read_bytes() == (ROOT / "backend/schemas/action_contract.v1.json").read_bytes()


def test_historical_structural_parser_keeps_old_source_compatible():
    raw = {"entry_node": "tap", "nodes": [{"id": "tap", "action": {"type": "tap"}, "on_success": "end"}, {"id": "end", "action": {"type": "end"}}]}
    historical = DAGScript.model_validate(raw).model_dump()
    assert historical["nodes"][0]["action"] == {"type": "tap"}
    assert concise(action_parameter_errors(historical["nodes"])) == ["x:required", "y:required"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_numbers_rejected(value):
    assert concise(action_parameter_errors([{"action": {"type": "scroll", "percent": value}}])) == ["percent:number"]


def test_huge_integer_does_not_crash_api_validator():
    assert concise(action_parameter_errors([{"action": {"type": "tap", "x": 10**1000, "y": 0}}])) == ["x:range"]


def test_direct_api_floating_integer_spelling_is_not_coerced_for_kotlin_int():
    assert concise(action_parameter_errors([{"action": {"type": "tap", "x": 1.0, "y": 0}}])) == ["x:integer"]


def test_unicode_length_measures_codepoints_and_empty_strings_are_explicit_values():
    assert action_parameter_errors([{"action": {"type": "type_text", "text": "😀" * 65536}}]) == []
    assert concise(action_parameter_errors([{"action": {"type": "type_text", "text": "😀" * 65537}}])) == ["text:length"]


def test_errors_and_candidate_walks_are_bounded():
    assert len(action_parameter_errors([{"action": {"type": "tap"}}] * 500)) == 100
    assert concise(action_parameter_errors([{"action": {"type": "find_first_element", "candidates": [{}] * 65}}])) == ["candidates:length"]
