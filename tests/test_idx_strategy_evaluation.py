"""Synthetic reference outcomes; no provider or network access."""
from tradingagents.idx_strategies.evaluation import evaluate


def observation(day, strategy="day", **changes):
    row: dict = {
        "strategy": strategy,
        "session_date": f"2026-10-{day:02d}",
        "observed_at": f"2026-10-{day:02d}T10:00:00+07:00",
        "planned_exit": f"2026-10-{day:02d}T15:00:00+07:00",
        "status": "EXITED",
        "gross_return": "0.02",
        "net_return": "0.01",
    }
    row.update(changes)
    return row


def test_chronological_split_preserves_strategy_summaries_and_session_groups():
    rows = [observation(day, strategy) for day in range(1, 11)
            for strategy in ("day", "overnight")]
    result = evaluate(reversed(rows))
    assert result["strategies"]["day"]["observations"] == 10
    assert result["split"]["status"] == "available"
    assert result["split"]["discovery_dates"] == [f"2026-10-{d:02d}" for d in range(1, 9)]
    assert result["split"]["holdout_dates"] == ["2026-10-09", "2026-10-10"]
    for strategy in ("day", "overnight"):
        assert result["cohorts"]["discovery"]["strategies"][strategy]["observations"] == 8
        assert result["cohorts"]["holdout"]["strategies"][strategy]["observations"] == 2
    assert result == evaluate(rows)


def test_date_fallback_uses_jakarta_observation_date_and_reports_unclassified():
    rows = [observation(day) for day in range(1, 6)]
    for row in rows:
        row.pop("session_date")
    # UTC evening is already the next Jakarta session date.
    rows[-1]["observed_at"] = "2026-10-04T20:00:00+00:00"
    undated = observation(6, session_date=None, observed_at=None)
    malformed = observation(7, session_date="invalid", observed_at="invalid")
    result = evaluate(rows + [undated, malformed])
    assert result["split"]["holdout_dates"] == ["2026-10-05"]
    assert result["cohorts"]["holdout"]["strategies"]["day"]["observations"] == 1
    assert result["cohorts"]["unclassified"]["strategies"]["day"]["observations"] == 2
    assert result["strategies"]["day"]["observations"] == 7


def test_single_session_or_no_dates_cannot_claim_holdout_performance():
    for rows in ([], [observation(1), observation(1, strategy="overnight")],
                 [observation(1, session_date=None, observed_at=None)]):
        result = evaluate(rows)
        assert result["split"]["status"] == "insufficient_data"
        assert result["split"]["holdout_dates"] == []
        for summary in result["cohorts"]["holdout"]["strategies"].values():
            assert summary["observations"] == 0
            assert summary["net_positive_fraction"] is None


def test_discovery_purges_planned_horizons_touching_first_holdout_observation():
    rows = [observation(day) for day in range(1, 6)]
    # Same instant as Oct 5 10:00 WIB; even an early actual exit cannot rescue it.
    rows[0].update(planned_exit="2026-10-05T03:00:00+00:00",
                   exited_at="2026-10-01T11:00:00+07:00")
    rows[1]["planned_exit"] = "2026-10-06T09:00:00+07:00"
    rows[2]["planned_exit"] = "2026-10-05T09:59:59+07:00"
    result = evaluate(rows)
    assert result["split"]["holdout_first_observation"] == "2026-10-05T10:00:00+07:00"
    assert result["cohorts"]["discovery"]["strategies"]["day"]["observations"] == 2
    assert result["cohorts"]["purged"]["strategies"]["day"]["observations"] == 2
    assert result["cohorts"]["holdout"]["strategies"]["day"]["observations"] == 1
    assert result["strategies"]["day"]["observations"] == 5


def test_missing_horizons_cannot_leak_into_discovery_and_date_only_boundary_is_conservative():
    rows = [observation(day) for day in range(1, 6)]
    rows[0]["planned_exit"] = None
    rows[1]["planned_exit"] = "2026-10-05T00:00:00+07:00"
    rows[-1]["observed_at"] = None
    result = evaluate(rows)
    assert result["cohorts"]["unclassified"]["strategies"]["day"]["observations"] == 1
    assert result["cohorts"]["purged"]["strategies"]["day"]["observations"] == 1
    assert result["cohorts"]["discovery"]["strategies"]["day"]["observations"] == 2
    assert result["split"]["boundary_basis"] == "conservative_session_start"
    assert result["split"]["holdout_first_observation"] is None


def test_existing_summary_excludes_pending_ambiguous_and_unknown_net_returns():
    rows = [observation(1, status="SETUP", net_return="99"),
            observation(2, status="AMBIGUOUS", gross_bounds=["-0.01", "0.02"]),
            observation(3, net_return=None), observation(4)]
    summary = evaluate(rows)["strategies"]["day"]
    assert summary["observations"] == 4
    assert summary["observable_closed"] == 2
    assert summary["net_observable"] == 1
    assert summary["net_unknown"] == 1
    assert summary["gross_mean"] == "0.02"
    assert summary["net_mean"] == "0.01"
    assert summary["net_positive_fraction"] == "1"
    assert summary["ambiguous_bounds"] == [["-0.01", "0.02"]]
    assert evaluate([observation(1, net_return=None)])["strategies"]["day"]["net_mean"] is None


def test_cohort_membership_does_not_depend_on_outcomes_or_candidate_score():
    rows = [observation(day, score=day) for day in range(1, 11)]
    before = evaluate(rows)
    for row in rows:
        row.update(status="AMBIGUOUS", gross_return="-9", net_return="-9", score=100)
    after = evaluate(rows)
    assert before["split"] == after["split"]
    for cohort in before["cohorts"]:
        for strategy in ("day", "overnight"):
            assert (before["cohorts"][cohort]["strategies"][strategy]["observations"]
                    == after["cohorts"][cohort]["strategies"][strategy]["observations"])
