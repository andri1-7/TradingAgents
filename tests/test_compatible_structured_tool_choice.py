"""Wire-level regression tests for opt-in compatible-server schema forcing."""
import json

import httpx
import pytest
from pydantic import BaseModel

from tradingagents.llm_clients.factory import build_llm_kwargs, create_llm_client


class Probe(BaseModel):
    answer: str


def make_llm(**kwargs):
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        message = {"role": "assistant", "content": "ok"}
        if payload.get("tool_choice") == {"type": "function", "function": {"name": "Probe"}}:
            message = {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_probe", "type": "function", "function": {
                    "name": "Probe", "arguments": '{"answer":"ok"}'}}
            ]}
        return httpx.Response(200, json={"id": "probe", "object": "chat.completion",
            "created": 0, "model": "router-model", "choices": [
                {"index": 0, "finish_reason": "tool_calls" if "tool_calls" in message else "stop",
                 "message": message}]})

    llm = create_llm_client("openai_compatible", "router-model", base_url="http://test.invalid/v1",
        api_key="test-only", max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(respond)), **kwargs).get_llm()
    return llm, requests


def test_opt_in_forces_schema_tool_and_returns_validated_pydantic(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_STRUCTURED_OUTPUT_TOOL_CHOICE", raising=False)
    llm, requests = make_llm(structured_output_tool_choice="required")
    result = llm.with_structured_output(Probe, include_raw=True).invoke("Return ok")
    assert isinstance(result["parsed"], Probe)
    assert result["parsed"].answer == "ok"
    assert result["parsing_error"] is None
    assert requests[0]["tool_choice"] == {"type": "function", "function": {"name": "Probe"}}
    assert "structured_output_tool_choice" not in requests[0]


@pytest.mark.parametrize("policy", [None, "auto"])
def test_default_and_auto_preserve_unforced_server_behavior(monkeypatch, policy):
    monkeypatch.delenv("TRADINGAGENTS_STRUCTURED_OUTPUT_TOOL_CHOICE", raising=False)
    llm, requests = make_llm(**({"structured_output_tool_choice": policy} if policy else {}))
    assert llm.with_structured_output(Probe).invoke("Return ok") is None
    assert "tool_choice" not in requests[0]


def test_explicit_config_overrides_environment(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_STRUCTURED_OUTPUT_TOOL_CHOICE", "required")
    llm, requests = make_llm(structured_output_tool_choice="auto")
    llm.with_structured_output(Probe).invoke("Return ok")
    assert "tool_choice" not in requests[0]


def test_explicit_per_call_choice_is_preserved():
    llm, requests = make_llm(structured_output_tool_choice="required")
    llm.with_structured_output(Probe, tool_choice=None).invoke("Return ok")
    assert "tool_choice" not in requests[0]


@pytest.mark.parametrize("policy", ["typo", "", True])
def test_invalid_policy_fails_before_network(policy):
    with pytest.raises(ValueError, match="structured_output_tool_choice"):
        make_llm(structured_output_tool_choice=policy)


def test_json_mode_is_not_given_tool_choice():
    llm, requests = make_llm(structured_output_tool_choice="required")
    llm.with_structured_output(Probe, method="json_mode", include_raw=True).invoke("Return JSON")
    assert "tool_choice" not in requests[0]
    assert requests[0]["response_format"] == {"type": "json_object"}


def test_config_forwards_policy_only_for_local_compatible_providers():
    assert build_llm_kwargs({"llm_provider": "openai_compatible", "structured_output_tool_choice": "required"}) == {"structured_output_tool_choice": "required"}
    assert build_llm_kwargs({"llm_provider": "ollama", "structured_output_tool_choice": "auto"}) == {"structured_output_tool_choice": "auto"}
    assert build_llm_kwargs({"llm_provider": "openai", "structured_output_tool_choice": "required"}) == {}


def test_environment_enables_schema_forcing(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_STRUCTURED_OUTPUT_TOOL_CHOICE", "required")
    llm, requests = make_llm()
    assert isinstance(llm.with_structured_output(Probe).invoke("Return ok"), Probe)
