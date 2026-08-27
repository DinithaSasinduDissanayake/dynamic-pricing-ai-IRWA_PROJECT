"""Drift guard: tool schemas, Pydantic models, and implementations must agree.

This is the structural defense against "phantom tools" — a schema advertising
arguments (or a whole tool) the implementation cannot honor.
"""
import inspect
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

import pytest

from core.agents.user_interact.tools import TOOLS_MAP
from core.agents.user_interact.tool_models import TOOL_MODELS, validate_tool_args
from core.agents.user_interact.tool_schemas import TOOL_SCHEMAS, EXPOSED_TOOLS


def _schema_by_name():
    return {t["function"]["name"]: t["function"] for t in TOOL_SCHEMAS}


def test_every_tools_map_entry_has_a_model_and_vice_versa():
    assert set(TOOLS_MAP.keys()) == set(TOOL_MODELS.keys())


def test_every_exposed_schema_has_model_and_implementation():
    schemas = _schema_by_name()
    assert set(schemas.keys()) == set(EXPOSED_TOOLS)
    for name in EXPOSED_TOOLS:
        assert name in TOOL_MODELS, f"exposed tool {name} has no Pydantic model"
        assert name in TOOLS_MAP, f"exposed tool {name} has no implementation"


@pytest.mark.parametrize("name", sorted(TOOL_MODELS.keys()))
def test_model_fields_accepted_by_implementation_signature(name):
    impl = TOOLS_MAP[name]
    sig = inspect.signature(impl)
    accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    for field in TOOL_MODELS[name].model_fields:
        assert accepts_kwargs or field in sig.parameters, (
            f"model field '{field}' of {name} not accepted by implementation {impl.__name__}{sig}"
        )
    # And every required implementation parameter must be a required model field.
    for pname, param in sig.parameters.items():
        if param.default is inspect.Parameter.empty and param.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY
        ):
            field = TOOL_MODELS[name].model_fields.get(pname)
            assert field is not None and field.is_required(), (
                f"implementation of {name} requires '{pname}' but the model does not"
            )


@pytest.mark.parametrize("name", EXPOSED_TOOLS)
def test_schemas_are_strict_and_closed(name):
    fn = _schema_by_name()[name]
    params = fn["parameters"]
    assert fn.get("strict") is True
    assert params["additionalProperties"] is False
    # Strict-mode rule: every property is listed in required.
    assert set(params["required"]) == set(params["properties"].keys())
    # No unresolved refs — nested models would silently break providers.
    blob = repr(params)
    assert "$ref" not in blob and "$defs" not in blob
    # No defaults/titles leak into the wire schema.
    assert "'default'" not in blob and "'title'" not in blob
    assert fn.get("description"), f"{name} schema missing description"


def test_validate_tool_args_rejects_bad_and_unknown_args():
    ok, err = validate_tool_args("optimize_price", {"sku": "X-1", "algorithm": "banana"})
    assert ok is False
    assert err["ok"] is False and "algorithm" in err["error"]
    assert "expected" in err

    ok, err = validate_tool_args("get_portfolio_urgency", {"bogus": 1})
    assert ok is False and "bogus" in err["error"]

    ok, cleaned = validate_tool_args("optimize_price", {"sku": "X-1", "algorithm": None})
    assert ok is True and cleaned == {"sku": "X-1"}
