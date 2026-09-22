"""Unit tests for the perf graph's knob handling and timing middleware. No server, no model key."""

from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage
from prometheus_client import REGISTRY

from my_agent.perf import FACTORY_DELAY_MAX_MS, TOOLS, _knobs
from my_agent.telemetry import TimedModelCall


def test_knobs_defaults_when_configurable_missing():
    k = _knobs({})
    assert k.tools == tuple(TOOLS)
    assert k.factory_delay_ms == 0
    assert ":" in k.model  # provider:model form


def test_knobs_clamp_and_validate():
    k = _knobs({"configurable": {"factory_delay_ms": 99999, "tools": "worker_id,not_a_tool", "model": "bad model!"}})
    assert k.factory_delay_ms == FACTORY_DELAY_MAX_MS
    assert k.tools == ("worker_id",)  # unknown names are dropped
    assert " " not in k.model  # invalid model string falls back to the default


def test_knobs_invalid_tools_keep_topology():
    k = _knobs({"configurable": {"tools": "nothing_valid", "factory_delay_ms": "-5"}})
    assert k.tools == tuple(TOOLS)  # never an empty tool list
    assert k.factory_delay_ms == 0


def _count(first: str) -> float:
    return REGISTRY.get_sample_value("agent_model_call_duration_ms_count", {"first": first}) or 0.0


def test_timed_model_call_records_first_turn():
    before = _count("true")
    request = SimpleNamespace(messages=[HumanMessage(content="hi")])
    out = TimedModelCall().wrap_model_call(request, lambda req: AIMessage(content="hello"))
    assert out.content == "hello"
    assert _count("true") == before + 1


def test_timed_model_call_records_later_turns():
    before = _count("false")
    request = SimpleNamespace(messages=[HumanMessage(content="hi"), AIMessage(content="tool call done")])
    TimedModelCall().wrap_model_call(request, lambda req: AIMessage(content="ok"))
    assert _count("false") == before + 1
