"""Offline tests: no live model or market requests."""
import copy
import importlib
import importlib.util

import pytest


def feature():
    assert importlib.util.find_spec("tradingagents.agents.jev_decision") is not None, "Jev final decision is missing"
    return importlib.import_module("tradingagents.agents.jev_decision")


def test_final_decision_uses_existing_client_with_bounded_reports(monkeypatch):
    module = feature()
    monkeypatch.setenv("TYPESAFE_API_KEY", "offline-test-key")
    monkeypatch.delenv("TYPESAFE_DEFAULT_MODEL", raising=False)
    calls = []
    answer = {"type": "choice", "choice": "BUY", "probabilities": {"BUY": 0.7, "HOLD": 0.2, "SELL": 0.1}, "confidence": 0.8}
    def ask(state, questions):
        calls.append((state, questions))
        return {"decision": answer}
    monkeypatch.setattr(module, "system_one", ask)
    result = module.decide("BBCA.JK", "2026-01-15", {"final_trade_decision": "x" * 50000, "market_report": "market", "credentials": "secret", "messages": ["secret"], "news_report": {"unexpected": "secret"}})
    sent, questions = calls[0]
    assert sent["ticker"] == "BBCA.JK"
    assert sent["as_of"] == "2026-01-15"
    assert set(sent) == {"ticker", "as_of", "reports"}
    assert set(sent["reports"]) == {"final_trade_decision", "market_report"}
    assert len(sent["reports"]["final_trade_decision"]) == module.MAX_REPORT_CHARS
    assert questions["decision"]["type"] == "choice"
    assert set(questions["decision"]["criteria"]) == {"BUY", "HOLD", "SELL"}
    assert "existing" in questions["decision"]["criteria"]["SELL"]
    assert "short" in questions["decision"]["criteria"]["SELL"]
    assert result["decision"] == answer
    assert result["requested_model"] == "jev-latest"
    assert result["resolved_model"] is None
    assert result["ticker"] == "BBCA.JK"


@pytest.mark.parametrize("change", [
    {"choice": "hold"}, {"choice": "SHORT"}, {"choice": True}, {"type": "noul"},
    {"probabilities": {"BUY": 0.7, "HOLD": 0.3}},
    {"probabilities": {"BUY": 0.7, "HOLD": 0.2, "SELL": 0.1, "OTHER": 0}},
    {"probabilities": {"BUY": True, "HOLD": 0, "SELL": 0}},
    *[{"probabilities": {"BUY": value, "HOLD": 0.2, "SELL": 0.1}}
      for value in [float("nan"), float("inf"), -0.1, 1.1, "0.7", 0.6]],
    *[{"confidence": value} for value in [True, None, "0.8", float("nan"), float("inf"), -0.1, 1.1]],
    {"confidence": "MISSING"},
])
def test_malformed_decisions_fail_closed(monkeypatch, change):
    module = feature()
    monkeypatch.setenv("TYPESAFE_API_KEY", "offline-test-key")
    answer = {"type": "choice", "choice": "BUY", "probabilities": {"BUY": 0.7, "HOLD": 0.2, "SELL": 0.1}, "confidence": 0.8}
    answer.update(copy.deepcopy(change))
    if answer["confidence"] == "MISSING":
        del answer["confidence"]
    monkeypatch.setattr(module, "system_one", lambda *a: {"decision": answer})
    from tradingagents.agents.post_screen import TypeSafeError
    with pytest.raises(TypeSafeError, match="invalid Jev decision"):
        module.decide("BBCA.JK", "2026-01-15", {"final_trade_decision": "report"})


def test_opt_in_runs_after_graph_and_saves_separate_artifact(monkeypatch, tmp_path, capsys):
    import json

    from tradingagents import indonesia
    from tradingagents.graph import trading_graph
    module = feature()
    monkeypatch.setenv("TYPESAFE_API_KEY", "offline-test-key")
    config = indonesia.build_indonesia_config()
    config["results_dir"] = str(tmp_path)
    monkeypatch.setattr(indonesia, "build_indonesia_config", lambda: config)
    events = []
    original = {"final_trade_decision": "Original report", "market_report": "Market"}
    class Graph:
        def __init__(self, **kwargs):
            events.append("graph")
        def propagate(self, ticker, as_of):
            events.append("analysis")
            return original, "HOLD"
    monkeypatch.setattr(trading_graph, "TradingAgentsGraph", Graph)
    def ask(state, questions):
        events.append("jev")
        assert state["reports"]["final_trade_decision"] == "Original report"
        return {"decision": {"type": "choice", "choice": "SELL", "probabilities": {"BUY": 0.1, "HOLD": 0.2, "SELL": 0.7}, "confidence": 0.9}}
    monkeypatch.setattr(module, "system_one", ask)
    assert indonesia.main(["--ticker", "BBCA", "--date", "2026-01-15", "--jev-decision"]) == 0
    assert events == ["graph", "analysis", "jev"]
    artifacts = list(tmp_path.rglob("jev_decision*.json"))
    assert len(artifacts) == 1
    saved = json.loads(artifacts[0].read_text())
    assert saved["decision"]["choice"] == "SELL"
    assert saved["original_model_rating"] == "HOLD"
    assert saved["original_model_report"] == "Original report"
    assert saved["ticker"] == "BBCA.JK"
    assert original == {"final_trade_decision": "Original report", "market_report": "Market"}
    out = capsys.readouterr().out
    assert "Original model" in out and "HOLD" in out
    assert "Jev final decision: SELL" in out


@pytest.mark.parametrize("key", [None, "", "   "])
def test_missing_key_rejected_before_main_graph(monkeypatch, key, capsys):
    from tradingagents import indonesia
    from tradingagents.graph import trading_graph
    if key is None:
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    else:
        monkeypatch.setenv("TYPESAFE_API_KEY", key)
    monkeypatch.setattr(trading_graph, "TradingAgentsGraph", lambda **k: pytest.fail("paid graph constructed"))
    assert indonesia.main(["--ticker", "BBCA", "--date", "2026-01-15", "--jev-decision"]) == 1
    assert "TYPESAFE_API_KEY" in capsys.readouterr().err


def test_direct_call_without_key_never_sends_request(monkeypatch):
    module = feature()
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(module, "system_one", lambda *a: pytest.fail("request without key"))
    with pytest.raises(module.TypeSafeError, match="TYPESAFE_API_KEY"):
        module.decide("BBCA.JK", "2026-01-15", {"final_trade_decision": "report"})


@pytest.mark.parametrize("failure", ["api", "malformed", "disk", "partial_write", "replace_permission"])
def test_cli_failure_has_no_guessed_decision_or_success_artifact(monkeypatch, tmp_path, capsys, failure):
    from tradingagents import indonesia
    from tradingagents.graph import trading_graph
    module = feature()
    monkeypatch.setenv("TYPESAFE_API_KEY", "offline-test-key")
    config = indonesia.build_indonesia_config()
    config["results_dir"] = str(tmp_path)
    if failure == "disk":
        blocked = tmp_path / "blocked"
        blocked.write_text("file")
        config["results_dir"] = str(blocked)
    monkeypatch.setattr(indonesia, "build_indonesia_config", lambda: config)
    class Graph:
        def __init__(self, **kwargs):
            pass
        def propagate(self, *args):
            return {"final_trade_decision": "original report"}, "BUY"
    monkeypatch.setattr(trading_graph, "TradingAgentsGraph", Graph)
    def ask(*args):
        if failure == "api":
            raise module.TypeSafeError("HTTP 401")
        if failure == "malformed":
            return {"decision": {}}
        return {"decision": {"type": "choice", "choice": "HOLD", "probabilities": {"BUY": 0, "HOLD": 1, "SELL": 0}, "confidence": 1}}
    monkeypatch.setattr(module, "system_one", ask)
    if failure == "partial_write":
        from pathlib import Path

        write_text = Path.write_text

        def partial_write(path, data, **kwargs):
            write_text(path, data[:177], **kwargs)
            raise OSError("disk full after partial write")

        monkeypatch.setattr(Path, "write_text", partial_write)
    elif failure == "replace_permission":
        import os

        def denied_replace(source, target):
            assert source.is_file()
            raise PermissionError("artifact publication denied")

        monkeypatch.setattr(os, "replace", denied_replace)
    assert indonesia.main(["--ticker", "BBCA", "--date", "2026-01-15", "--jev-decision"]) == 1
    captured = capsys.readouterr()
    assert "JEV_UNAVAILABLE" in captured.err
    assert "Jev final decision:" not in captured.out
    assert "Original model rating: BUY" in captured.out
    assert not list(tmp_path.rglob("jev_decision*.json"))
    assert not list(tmp_path.rglob("*.tmp"))
    assert "Jev artifact:" not in captured.out


def test_no_final_report_fails_before_request(monkeypatch):
    module = feature()
    monkeypatch.setenv("TYPESAFE_API_KEY", "offline-test-key")
    monkeypatch.setattr(module, "system_one", lambda *a: pytest.fail("missing final report"))
    with pytest.raises(module.TypeSafeError, match="final report"):
        module.decide("BBCA.JK", "2026-01-15", {"market_report": "market"})


@pytest.mark.parametrize("mode", ["default", "check"])
def test_no_jev_requests_without_opt_in_or_in_check_data(monkeypatch, capsys, mode):
    import pandas as pd

    from tradingagents import indonesia
    from tradingagents.graph import trading_graph
    module = feature()
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(module, "system_one", lambda *a: pytest.fail("unexpected Jev request"))
    class Graph:
        def __init__(self, **kwargs):
            if mode == "check":
                pytest.fail("check-data constructed graph")
        def propagate(self, *args):
            return {"final_trade_decision": "report"}, "BUY"
    monkeypatch.setattr(trading_graph, "TradingAgentsGraph", Graph)
    monkeypatch.setattr("tradingagents.dataflows.vendors.yahoo.ohlcv.load_ohlcv", lambda *a, **k: pd.DataFrame({"Date": pd.to_datetime(["2026-01-15"]), "Close": [9100]}))
    args = ["--ticker", "BBCA", "--date", "2026-01-15"]
    if mode == "check":
        args += ["--check-data", "--jev-decision"]
    assert indonesia.main(args) == 0
    assert "Jev final decision:" not in capsys.readouterr().out


def test_existing_client_request_shape_and_model_provenance(monkeypatch):
    from tradingagents.agents import post_screen
    module = feature()
    monkeypatch.setenv("TYPESAFE_API_KEY", "offline-test-key")
    monkeypatch.setenv("TYPESAFE_DEFAULT_MODEL", "jev-test-alias")
    monkeypatch.delenv("TYPESAFE_BASE_URL", raising=False)
    calls = []
    class Response:
        status_code = 200
        def json(self):
            return {"model": "resolved-server-model", "answers": {"decision": {"type": "choice", "choice": "HOLD", "probabilities": {"BUY": 0, "HOLD": 1, "SELL": 0}, "confidence": 1}}}
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()
    monkeypatch.setattr(post_screen.requests, "post", post)
    result = module.decide("BBCA.JK", "2026-01-15", {"final_trade_decision": "report"})
    url, kwargs = calls[0]
    assert url == "https://api.typesafe.ai/v1/systemone"
    assert kwargs["json"]["model"] == "jev-test-alias"
    assert kwargs["headers"]["Authorization"] == "Bearer offline-test-key"
    assert result["requested_model"] == "jev-test-alias"
    assert result["resolved_model"] is None  # Shared client discards this metadata.


def test_remote_extra_fields_are_not_persisted(monkeypatch):
    module = feature()
    monkeypatch.setenv("TYPESAFE_API_KEY", "offline-test-key")
    monkeypatch.setattr(module, "system_one", lambda *a: {"decision": {"type": "choice", "choice": "HOLD", "probabilities": {"BUY": 0, "HOLD": 1, "SELL": 0}, "confidence": 1, "untrusted": "extra"}})
    result = module.decide("BBCA.JK", "2026-01-15", {"final_trade_decision": "report"})
    assert set(result["decision"]) == {"type", "choice", "probabilities", "confidence"}
