"""Offline adapter contracts: graph and Jev transports are never called live."""

from copy import deepcopy
from datetime import datetime

import pytest


@pytest.fixture(autouse=True)
def no_live_credentials(monkeypatch):
    monkeypatch.setenv("DOTENV_DISABLED", "1")
    monkeypatch.setenv("TYPESAFE_API_KEY", "")


@pytest.mark.parametrize("failure", ["graph", "jev", "injection"])
def test_failures_are_safe_and_keep_completed_reports(monkeypatch, failure):
    from tradingagents.idx_strategies import ai_analysis as ai

    candidate = {
        "symbol": "BBCA.JK",
        "session_date": "2026-10-27",
        "signal_time": "2026-10-27T09:35:00+07:00",
    }

    class Graph:
        def __init__(self, **kwargs):
            self.config = kwargs["config"]
            assert self.config["memory_log_path"] != "/private/shared.md"

        def create_run_state(self, *args):
            return {"instrument_context": "identity"}

        def propagate(self, *args):
            if failure == "graph":
                raise RuntimeError("SECRET API KEY")
            if failure != "injection":
                self.create_run_state(*args)
            return {"final_trade_decision": "Hold", "news_report": "Unavailable"}, "Hold"

    monkeypatch.setattr(ai, "TradingAgentsGraph", Graph)

    def jev(*args):
        raise RuntimeError("SECRET API KEY")

    monkeypatch.setattr(ai, "decide", jev)
    result = ai.analyze_candidate(candidate, config={"memory_log_path": "/private/shared.md"})
    assert "SECRET" not in str(result)
    assert result["analysis_completed_at"]
    if failure == "jev":
        assert result["status"] == "partial"
        assert result["reports"]["news_report"] == "Unavailable"
        assert result["jev"]["error_class"] == "jev_unavailable"
    else:
        assert result["status"] == "unavailable"
        assert result["error_class"] in ("analysis_unavailable", "evidence_injection_unavailable")
        assert result["jev"]["status"] == "not_run"


@pytest.mark.parametrize(
    "changes",
    [
        {"symbol": "BBCA"},
        {"session_date": "20261027"},
        {"signal_time": "2026-10-27T09:35:00"},
        {"session_date": "2099-01-01"},
    ],
)
def test_invalid_input_fails_before_paid_graph(monkeypatch, changes):
    from tradingagents.idx_strategies import ai_analysis as ai

    candidate = {
        "symbol": "BBCA.JK",
        "session_date": "2026-10-27",
        "signal_time": "2026-10-27T09:35:00+07:00",
    }
    candidate.update(changes)

    def forbidden(**kwargs):
        pytest.fail("Invalid input must not construct a graph")

    monkeypatch.setattr(ai, "TradingAgentsGraph", forbidden)
    result = ai.analyze_candidate(candidate)
    assert result["status"] == "unavailable"
    assert result["error_class"] == "invalid_candidate"


def test_no_setup_control_uses_observation_without_inventing_signal(monkeypatch):
    from tradingagents.idx_strategies import ai_analysis as ai

    seen = []

    class Graph:
        def __init__(self, **kwargs):
            seen.append(True)

        def create_run_state(self, *args):
            return {"instrument_context": "identity"}

        def propagate(self, *args):
            self.create_run_state(*args)
            return {"final_trade_decision": "Hold"}, "Hold"

    monkeypatch.setattr(ai, "TradingAgentsGraph", Graph)
    monkeypatch.setattr(ai, "decide", lambda *args: {"decision": {"choice": "HOLD"}})
    result = ai.analyze_candidate(
        {
            "symbol": "AADI.JK",
            "session_date": "2026-10-27",
            "status": "NO_SETUP",
            "signal_time": None,
            "observed_at": "2026-10-27T09:35:00+07:00",
        }
    )
    assert seen
    assert result["status"] == "completed"
    assert result["signal_time"] is None
    assert result["integration_validation_only"] is True


def test_real_memory_node_cannot_settle_shared_decisions(monkeypatch):
    from tradingagents.idx_strategies import ai_analysis as ai

    real_graph = ai.TradingAgentsGraph
    captured = {}

    class Graph:
        _memory_as_of = real_graph._memory_as_of

        def __init__(self, **kwargs):
            class Memory:
                def get_past_context(self, *args, **kwargs):
                    return ""

            self.memory_log = Memory()

        def settle_all_pending(self, **kwargs):
            pytest.fail("Paid settlement must be disabled")

        def create_run_state(self, *args):
            return {"instrument_context": "identity"}

        def propagate(self, symbol, day):
            self.create_run_state(symbol, day)
            captured.update(
                real_graph._memory_step(self, {"company_of_interest": symbol, "trade_date": day})
            )
            return {"final_trade_decision": "Hold"}, "Hold"

    monkeypatch.setattr(ai, "TradingAgentsGraph", Graph)
    monkeypatch.setattr(ai, "decide", lambda *args: {})
    result = ai.analyze_candidate(
        {
            "symbol": "BBCA.JK",
            "session_date": "2026-10-27",
            "signal_time": "2026-10-27T09:35:00+07:00",
        }
    )
    assert result["status"] == "completed"
    assert captured == {"past_context": "", "memory_note": ""}


def test_environment_endpoint_retained_and_config_not_mutated(monkeypatch):
    from tradingagents.idx_strategies import ai_analysis as ai

    monkeypatch.setenv("TRADINGAGENTS_LLM_BACKEND_URL", "http://local9router.invalid/v1")
    cfg = {"max_tool_rounds": 2}

    class Graph:
        def __init__(self, **kwargs):
            assert kwargs["config"]["backend_url"] == "http://local9router.invalid/v1"
            raise RuntimeError("safe failure")

    monkeypatch.setattr(ai, "TradingAgentsGraph", Graph)
    ai.analyze_candidate(
        {
            "symbol": "BBCA.JK",
            "session_date": "2026-10-27",
            "signal_time": "2026-10-27T09:35:00+07:00",
        },
        config=cfg,
    )
    assert cfg == {"max_tool_rounds": 2}


def test_full_analysis_preserves_identity_evidence_and_separate_jev(monkeypatch):
    from tradingagents.idx_strategies import ai_analysis as ai

    candidate = {
        "symbol": "BBCA.JK",
        "session_date": "2026-10-27",
        "signal_time": "2026-10-27T09:35:00+07:00",
        "strategy": "opening_range",
        "evidence": {"timeframe": "5m", "closed_bar": True, "breakout": 9025},
    }
    original = deepcopy(candidate)
    captured = {}

    class Graph:
        def __init__(self, *, selected_analysts, config):
            captured.update(analysts=selected_analysts, config=config)

        def create_run_state(self, symbol, day, *args, **kwargs):
            return {
                "instrument_context": "Verified company identity",
                "company_of_interest": symbol,
            }

        def propagate(self, symbol, day):
            captured["settlement_disabled"] = not self.settle_all_pending(wait=False).failed
            captured["identity"] = (symbol, day)
            captured["initial"] = self.create_run_state(symbol, day)
            return {
                "market_report": "Observed daily market report",
                "news_report": "Unavailable",
                "fundamentals_report": "No issuer evidence",
                "final_trade_decision": "Hold",
            }, "Hold"

    def jev(symbol, day, state):
        captured["jev"] = (symbol, day, deepcopy(state))
        return {"decision": {"choice": "HOLD", "confidence": 0.8}}

    monkeypatch.setattr(ai, "TradingAgentsGraph", Graph)
    monkeypatch.setattr(ai, "decide", jev)
    result = ai.analyze_candidate(
        candidate, config={"backend_url": "http://local9router.invalid/v1"}
    )
    assert result["status"] == "completed"
    assert captured["identity"] == ("BBCA.JK", "2026-10-26")
    assert result["daily_as_of_session"] == "2026-10-26"
    assert captured["jev"][:2] == ("BBCA.JK", "2026-10-27")
    assert captured["config"]["max_recur_limit"] == 32
    assert captured["config"]["max_tokens"] == 2000
    assert captured["settlement_disabled"]
    assert captured["analysts"] == ("market", "news", "fundamentals")
    cfg = captured["config"]
    assert cfg["market"] == "IDX"
    for tier in ("deep", "quick"):
        assert cfg[f"{tier}_think_llm"] == "cx/gpt-6.1-sol"
        assert cfg[f"{tier}_think_provider"] == "openai_compatible"
    assert cfg["backend_url"] == "http://local9router.invalid/v1"
    assert cfg["checkpoint_enabled"] is False
    context = captured["initial"]["instrument_context"]
    assert "Verified company identity" in context
    assert '"breakout": 9025' in context
    assert "not an intraday entry decision" in context
    assert result["reports"]["news_report"] == "Unavailable"
    assert result["rating"] == "Hold"
    assert result["jev"]["result"]["decision"]["choice"] == "HOLD"
    assert result["context"] == "daily_supporting_analysis_not_entry_decision"
    assert result["intraday_validity"] == "not_assessed"
    assert result["revalidation_required"] is True
    assert result["strategy_evidence_injected"] is True
    assert result["signal_time"] == candidate["signal_time"]
    assert datetime.fromisoformat(result["analysis_started_at"]) <= datetime.fromisoformat(
        result["analysis_completed_at"]
    )
    assert "9025" in captured["jev"][2]["final_trade_decision"]
    assert candidate == original
