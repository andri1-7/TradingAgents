"""Offline regression coverage for IDX snapshot starvation at the round cap."""
from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableLambda

import tradingagents.agents.analysts.market_analyst as market
import tradingagents.agents.tools as tools
from tradingagents.agents.analysts.turn import WRAP_UP
from tradingagents.dataflows.errors import VendorUnavailableError

DAY = "2026-10-27"


def _history():
    messages = [HumanMessage(content="Analyze BBCA.JK")]
    for i, name in enumerate(["get_stock_data", *(["get_indicators"] * 3)]):
        messages.extend([
            AIMessage(content="", tool_calls=[{"id": str(i), "name": name, "args": {}}]),
            ToolMessage(content="prior data", tool_call_id=str(i), name=name),
        ])
    return [*messages, HumanMessage(content=WRAP_UP)]


def _run(monkeypatch, messages, symbol="BBCA.JK"):
    monkeypatch.setattr(market, "get_instrument_context_from_state", lambda state: "instrument")
    monkeypatch.setattr(market, "get_language_instruction", lambda: "")
    captured = []

    def respond(prompt):
        captured.append(prompt.to_messages())
        return AIMessage(content="Final market report")

    llm = RunnableLambda(respond)
    llm.bind_tools = Mock(side_effect=AssertionError("wrap-up must not bind tools"))
    state = {"company_of_interest": symbol, "trade_date": DAY, "messages": messages}
    result = market.create_market_analyst(llm)(state)
    return result, captured, llm


def test_idx_wrap_up_fetches_missing_snapshot_before_only_final_llm_call(monkeypatch):
    snapshot = Mock(return_value="verified snapshot payload")
    monkeypatch.setattr(market.get_verified_market_snapshot, "func", snapshot)
    messages = _history()
    original = list(messages)

    result, captured, llm = _run(monkeypatch, messages)

    snapshot.assert_called_once_with(symbol="BBCA.JK", curr_date=DAY, trade_date=DAY)
    assert len(captured) == 1
    text = "\n".join(m.content for m in captured[0])
    assert "verified snapshot payload" in text
    assert captured[0][-1].content == WRAP_UP
    assert result["market_report"] == "Final market report"
    assert messages == original  # Never mutate graph state in place.
    assert any("verified snapshot payload" in m.content for m in result["messages"])
    llm.bind_tools.assert_not_called()


@pytest.mark.parametrize("error_type", [RuntimeError, VendorUnavailableError])
def test_idx_wrap_up_injects_explicit_unavailability_on_fetch_failure(monkeypatch, error_type):
    fetch = Mock(side_effect=error_type("vendor connection failed"))
    monkeypatch.setattr(tools, "build_verified_market_snapshot", fetch)

    result, captured, _ = _run(monkeypatch, _history())

    fetch.assert_called_once_with("BBCA.JK", DAY, 30)
    text = "\n".join(m.content for m in captured[0])
    assert "get_verified_market_snapshot" in text
    assert "unavailable" in text.lower()
    assert "vendor connection failed" in text
    assert len(captured) == 1
    assert result["market_report"] == "Final market report"


@pytest.mark.parametrize("prior_kind", ["tool", "call", "injected"])
def test_idx_wrap_up_does_not_repeat_existing_snapshot(monkeypatch, prior_kind):
    snapshot = Mock(side_effect=AssertionError("snapshot must not be fetched again"))
    monkeypatch.setattr(market.get_verified_market_snapshot, "func", snapshot)
    messages = _history()
    if prior_kind == "tool":
        prior = ToolMessage(content="prior verified data", name="get_verified_market_snapshot", tool_call_id="s")
    elif prior_kind == "call":
        prior = AIMessage(content="", tool_calls=[{"id": "s", "name": "get_verified_market_snapshot", "args": {}}])
    else:
        prior = HumanMessage(content="[get_verified_market_snapshot returned]\nprior verified data", name="get_verified_market_snapshot")
    messages.insert(-1, prior)

    result, captured, _ = _run(monkeypatch, messages)

    snapshot.assert_not_called()
    assert len(captured) == 1
    assert len(result["messages"]) == 1


def test_other_markets_keep_existing_wrap_up_behavior(monkeypatch):
    snapshot = Mock(side_effect=AssertionError("non-IDX must not fetch"))
    monkeypatch.setattr(market.get_verified_market_snapshot, "func", snapshot)

    result, captured, _ = _run(monkeypatch, _history(), symbol="AAPL")

    snapshot.assert_not_called()
    assert len(captured) == 1
    assert len(result["messages"]) == 1
