# IDX morning→afternoon and afternoon→next-morning strategy research

## Goal
Build a reproducible, observational IDX screener and shadow evaluator for two separate strategies—morning entry/afternoon exit and afternoon entry/next-session morning exit—without orders, invented fills, or claims of profitability.

## Current context / assumptions

- Workspace: `/root/projects/TradingAgents-indonesia`; clean when inspected on 2026-10-28. Existing feature branch: `feature/indonesia-idx-v071`; do not merge into main automatically.
- Python >=3.11. Verified interpreter: `/root/projects/TradingAgents/.venv/bin/python`. Use `PY=/root/projects/TradingAgents/.venv/bin/python` in shell examples below, from the workspace root.
- `tradingagents/idx_registry.py:load_registry()` returns a validated envelope with `issuers` containing `symbol`, `name`, `yahoo_symbol`; bundled snapshot has 962 entries but current completeness is explicitly unverified. Reuse it; do not hardcode a famous-stock universe.
- `tradingagents/indonesia.py` currently analyzes one ticker using the full LLM graph. `tradingagents/dataflows/vendors/yahoo/ohlcv.py` is a DAILY data cache. Neither is an intraday scanner. Do NOT reuse daily candles as intraday evidence.
- `tradingagents/agents/jev_decision.py` makes an optional final structured classification of reports; its confidence is NOT a profit probability. No LLM is necessary for this MVP. Do not run 962 full TradingAgents analyses.
- Existing private `.env` selects Sol 6.1 through localhost 9Router and a separate Jev key. Do not read values into artifacts, change routing, or invoke paid models for this work.
- Daily screen examples AADI/UNTR/PTBA were exploratory, not evidence that either proposed strategy works. Do not seed outcome statistics with them.
- User has not specified broker fees, capital, risk budget, or official current exchange calendar. Missing values must block net-performance claims, not become guessed defaults.
- Default delivery: local CLI plus durable SQLite. Telegram/Discord scheduling, actual broker integration, portfolio sizing and autonomous execution are OUT OF SCOPE.

## Architecture / proposed approach

Create an isolated `tradingagents/idx_strategies/` package: strict intraday data normalization, explicit exchange sessions, deterministic setup rules, immutable SQLite observations, and later outcomes. Use Yahoo only behind a provider adapter whose actual retention, interval conventions and availability are verified before admitting data; a bounded rotating registry universe exposes partial coverage instead of silently equating configured symbols with scanned symbols. Keep discovery, setup, hypothetical entry reference and outcome distinct; emit at most three candidate cards, never an order.

## Explicit product contract (do not improvise)

### Modes

1. `day`: evaluate after the first 30 minutes of continuous trading. A candidate requires an opening-range breakout followed by a later retest; plan time exit is 15 minutes before that session's continuous close.
2. `overnight`: evaluate 30 minutes before continuous close, use an entry decision at that instant, and time exit 30 minutes after the next session's continuous open. `next` comes from the supplied exchange-session calendar, not date+1. No Friday/holiday carry unless the calendar supplies the next session.
3. These are research policy defaults, NOT official trading hours or optimized rules. Use 5-minute bars with timestamps representing interval start; convert vendor conventions explicitly. Daily/weekly context may reject entries but cannot create intraday confirmations.
4. Selection instant is not execution. Enter only at the first available eligible bar OPEN strictly after the observation was durably recorded; never use a bar that had already opened. A missed entry deadline produces `UNOBSERVABLE`, not a late/backfilled fill.
5. The scheduler/invocation cadence must be fast enough to observe the selected window. Do not retroactively create a prospective observation from an earlier signal.

### Session input contract

A user-supplied, versioned JSON file contains exact continuous intervals and exchange-local dates. There is no bundled calendar guessed from weekdays. Schema:

```json
{
  "source_url": "https://official-source-used-by-the-operator.example/calendar",
  "retrieved_at": "2026-10-28T00:00:00+00:00",
  "timezone": "Asia/Jakarta",
  "sessions": [
    {"date":"2026-10-26","intervals":[["2026-10-26T09:00:00+07:00","2026-10-26T12:00:00+07:00"],["2026-10-26T13:30:00+07:00","2026-10-26T15:45:00+07:00"]]}
  ]
}
```

**The row above is a synthetic schema example, not a verified IDX schedule.** Production requires official current calendar/hours checked by the operator, including Friday differences, lunch breaks, holidays and auction phases. Do not include auctions in continuous intervals. Missing next-session data blocks overnight candidates. Reject overlapping intervals, duplicate sessions, naive timestamps, non-Jakarta dates, or close-before-open.

### Universe and provider contract

- Rotate through all registry identities in sorted order with a persisted cursor; default maximum 25 ticker history requests per scan, concurrency 2. A failed request consumes a slot. Configure request limits, never claim those are monetary limits.
- Persist cursor only together with scan records. A provider-wide failure must not skip unread symbols. A per-symbol result (including explicit error) is recorded before its cursor advances.
- Do not add a top-volume-only restriction as the sole discovery universe. Eligibility uses last completed data: prior 20-session median turnover proxy >= IDR10bn and raw last close >= IDR100; these are explicit research assumptions, configurable, not validated liquidity guarantees. Missing daily history → insufficient data.
- Turnover proxy is raw close×shares traded; it is NOT official traded value or order-book depth. Corporate action distortion must be flagged. Intraday executable references use unadjusted prices; no adjusted/raw mixing.
- API failure, empty history, stale history, incomplete sessions, unsupported interval and suspended trading are distinct statuses.
- Historical availability must be measured for the exact IDX symbols/provider. Never promise months of 5m data merely because a library accepts `period`.

### Setup rules v1

Shared gates: valid/contiguous required bars, valid daily context, eligible liquidity proxy, no known adjustment ambiguity, decision time within the designated window, risk/reward >=1.5 after supplied costs, positive risk distance <=2% of entry reference. Thresholds are versioned policy assumptions, not proven edge.

- `day`: opening range = first 30 trading minutes. Require a CLOSED bar above range high, then a later CLOSED bar touching range high within a configurable 0.2% tolerance and closing above it, bullish body, close above cumulative session VWAP, and volume >=1.5× median of the PRECEDING 20 valid 5m bars (exclude candidate bar; fewer than20 → insufficient). Evaluate only data known at observation. Entry is a future reference; stop is retest low; target is entry +1.5R. Risk gate computed at actual observed entry reference, not invented before it.
- `overnight`: at its decision instant, last CLOSED price > daily EMA20 and session VWAP; last bar closes in top25% of its session-to-date high/low range; preceding-20-bar relative volume >=1.5; price is no more than2% above EMA20. Daily EMA uses completed previous daily sessions only. Stop reference = last 30 trading-minute low; target = entry +1.5R. Reject gaps/insufficient bars rather than relaxing criteria.
- With no exact future entry price yet, persist `SETUP` plus reference close and provisional risk, NOT `ENTERED`. Re-evaluate risk gate at observed next-bar open. Invalid gap means `ENTRY_REJECTED`.
- For overnight, flag correlated sector exposure, earnings/corporate-event coverage unknown, and weekend/holiday holding span. Unknown events are never labeled checked-safe. Initial mode is shadow, so no mandate to create a BUY.
- Candidate score is deterministic 0–10 rubric evidence quality, not win probability. Persist component values. Rank only within strategy and scan, deterministic tie-break ticker. Maximum3 across combined strategies; dedupe ticker and prefer higher score; retain all assessments in DB, including no setup.

### Outcome rules

- Continue evaluating open observations even if symbol leaves shortlist or rotation.
- Scheduled exit uses first valid bar OPEN at/after the planned time, within10 trading minutes, otherwise unobservable. Record actual horizon and planned horizon.
- Stop gaps: next open below stop uses that OPEN as reference, never the stop price. Intrabar stop/target references are modeled only; touching is not proof of an executable fill.
- If one bar contains both stop and target, label `AMBIGUOUS`; exclude from headline win rate and report pessimistic/optimistic bounds separately. Never invent ordering from OHLC.
- Never traverse bars crossing lunch/overnight as if continuous. Overnight gap is explicit; daily strategy never carries by silently missing exit.
- Report gross reference return separately from net hypothetical return. Net requires operator-supplied buy/sell fee rates and adverse slippage for EACH leg; formula below. No position size or actual PnL unless separately authorized and implemented later.

## Shared exact types / formulas

Implement these first in `tradingagents/idx_strategies/models.py` (stdlib; no secrets/provider objects in records):

```python
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

class Status(StrEnum):
    NO_SETUP = "NO_SETUP"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    SETUP = "SETUP"
    ENTERED = "ENTERED"
    ENTRY_REJECTED = "ENTRY_REJECTED"
    EXITED = "EXITED"
    AMBIGUOUS = "AMBIGUOUS"
    UNOBSERVABLE = "UNOBSERVABLE"
    PROVIDER_ERROR = "PROVIDER_ERROR"

@dataclass(frozen=True)
class Bar:
    symbol: str
    start: datetime
    end: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

@dataclass(frozen=True)
class Costs:
    buy_fee: Decimal
    sell_fee: Decimal
    buy_slippage: Decimal
    sell_slippage: Decimal

def net_reference_return(entry: Decimal, exit: Decimal, costs: Costs) -> Decimal:
    values = (entry, exit, costs.buy_fee, costs.sell_fee,
              costs.buy_slippage, costs.sell_slippage)
    if not all(x.is_finite() for x in values):
        raise ValueError("non-finite price or cost")
    if entry <= 0 or exit <= 0:
        raise ValueError("prices must be positive")
    if not all(Decimal(0) <= x < Decimal(1) for x in values[2:]):
        raise ValueError("costs must be fractions in [0,1)")
    paid = entry * (1 + costs.buy_slippage) * (1 + costs.buy_fee)
    received = exit * (1 - costs.sell_slippage) * (1 - costs.sell_fee)
    return received / paid - 1
```

At transport/DB boundaries serialize decimals as strings and datetimes as ISO8601 with offset. Do not store floats in SQLite for money. All clocks injected in tests.

## Step-by-step implementation tasks

Every numbered item is one 2–5-minute slice. If a slice exceeds5 minutes, split into another RED→GREEN checkpoint before expanding scope. Do not write every test first then all implementation. Commits must contain passing tests; combine only the immediately adjacent tests/implementation pair when necessary.

### Phase A — prove data and build pure contracts

1. Read `tradingagents/idx_registry.py`, `tradingagents/dataflows/vendors/yahoo/ohlcv.py`, `tests/conftest.py`, and `pyproject.toml`. Run `git status --short` and `git log -1 --oneline`. Expected: identify baseline and preserve unrelated edits. No implementation yet.
2. Add `tests/test_idx_strategy_costs.py` with two assertions: zero-cost entry100→exit110 returns Decimal('0.1'); equal-price roundtrip with positive fees returns <0. Add parametrized NaN, infinite, zero prices, negative fees and fee>=1 rejection. Run `$PY -m pytest tests/test_idx_strategy_costs.py -q`: RED missing module/function. Create package `tradingagents/idx_strategies/__init__.py` and `models.py` using the complete code above. Re-run: GREEN all cases. Commit `feat(idx-research): define typed bars and reference costs`.
3. Add `tests/test_idx_intraday_provider.py` empty/malformed ticker tests for `fetch_intraday(symbol, start, end, interval='5m')` in `tradingagents/idx_strategies/provider.py`. Exact canonical `^[A-Z]{4}\.JK$`, explicit aware range, supported interval5m only; validation must happen before HTTP. RED, minimal adapter around `yf.Ticker(symbol).history(start=..., end=..., interval='5m', auto_adjust=False, actions=True, raise_errors=True)` with bounded exception categories and no retry loop; GREEN. Do not call network from unit tests.
4. Add offline tests for adapter timestamp mapping, split/dividend presence, empty history and exception sanitization. Implement normalized provider envelope with `source`, `retrieved_at` after fetch, `requested_range`, `interval`, `price_basis='raw'`, `corporate_actions`, `bars`, `status`. Provider exception messages must not include credentials. Verify same test command GREEN. Commit adapter.
5. Create `scripts/probe_idx_intraday.py`: argparse `--ticker` repeatable (default BBCA.JK,AADI.JK,UNTR.JK), `--output`, `--start`, `--end`; use adapter and write actual sanitized envelopes. No fabricated fixtures. Run `$PY scripts/probe_idx_intraday.py --start <aware-start> --end <aware-end> --output /tmp/idx-provider-probe.json` with explicit recent dates from `date`. Expected: parseable real envelopes or honest unavailable/error; inspect count/first/last/timezone and timestamp convention against provider docs. If all unavailable, STOP provider-dependent tasks and report blocker; allow offline core work but do not claim live-ready.
6. Add `tests/test_idx_bars.py` rejecting naive/off-grid time, interval !=5m, nonfinite/nonpositive OHLC, negative volume, OHLC inconsistency, conflicting duplicates and future/open bars. Implement `validate_bars(bars, observed_at, expected_intervals)` in `tradingagents/idx_strategies/bars.py`; exact duplicate can collapse only if all values identical. Return explicit rejection reasons, never fill missing bars. RED→GREEN. Commit.
7. Add tests requiring completeness only across supplied continuous intervals, not lunch or closed days. Implement expected-grid coverage checks in `bars.py`; distinguish symbol with no trades from missing data, do not interpolate. `$PY -m pytest tests/test_idx_bars.py -q` GREEN. Commit.

### Phase B — sessions and indicators

8. Add `tests/test_idx_sessions.py` synthetic Monday/Friday/lunch/holiday cases and invalid calendar cases from session contract above. Implement `load_sessions(path)` in `tradingagents/idx_strategies/sessions.py` with immutable sorted sessions; no network or weekday-generated fallback. RED→GREEN. Commit.
9. Test `next_session(day)` returns later supplied session, Friday→Monday and holiday→next actual session; last supplied date raises `MissingSession`. Implement. Verify `$PY -m pytest tests/test_idx_sessions.py -q`. Commit.
10. Test `decision_windows(session, strategy)` using first continuous open and final continuous close, proposed offsets above. Reject intervals too short. Implement session membership/trading-minute arithmetic for lunch-safe windows, including optional entry/exit grace. RED→GREEN. Commit.
11. Add `tests/test_idx_features.py` for exact Decimal VWAP (typical price=(H+L+C)/3 weighted by volume), zero total volume, previous20 volume baseline excludes current, daily EMA20 excludes current daily bar. Implement pure functions in `tradingagents/idx_strategies/features.py`; minimum history21 daily sessions; no LLM. RED→GREEN. Commit.

### Phase C — separate signal engines

12. Add `tests/test_idx_day_rules.py`: synthetic closed sequence opening range→breakout only must NOT signal; breakout→later valid retest signals; retest preceding breakout cannot signal. Implement `assess_day(...)` in `tradingagents/idx_strategies/rules.py` returning evidence/reasons/status. RED→GREEN. Commit.
13. Add same-day tests for VWAP, relative-volume/history, late-window, missing required bars and >2% risk rejection. Implement gates and deterministic score components; no partial-bar use. Verify `$PY -m pytest tests/test_idx_day_rules.py -q`. Commit.
14. Add `tests/test_idx_overnight_rules.py`: strong close +trend +volume qualifies, missing next session does not, low close location or overextension rejected. Implement `assess_overnight(...)` independently using shared features; no copy-pasted indicator math. RED→GREEN. Commit.
15. Add overnight cutoff tests: after-decision bars cannot affect classification; future/different-session volume cannot improve score; known adverse event veto versus unknown event label. Add `event_coverage='unknown'` default and explicit reasons, not an invented event feed. GREEN. Commit.
16. Add `tests/test_idx_strategy_ranking.py`: top3 combined maximum, unique ticker, stable sorting by score then ticker then strategy; all assessments retained separately. Implement `rank_candidates` in `rules.py`. GREEN. Commit.

### Phase D — durable observations and chronological outcomes

17. Add `tests/test_idx_strategy_store.py` with temporary SQLite: migration idempotence, run save/reload, decimal roundtrip. Implement `tradingagents/idx_strategies/store.py`. Tables: `scans(id, started_at, completed_at, source, rubric_version, requested, valid, failed, excluded, coverage_json)`; `assessments(scan_id,symbol,strategy,signal_time,status,evidence_json, UNIQUE(scan_id,symbol,strategy))`; `observations(id, symbol,strategy,session_date,observed_at,status,entry_deadline,planned_exit,entry_json,exit_json,costs_json,rubric_version, UNIQUE(symbol,strategy,session_date,rubric_version))`; `rotation(name PRIMARY KEY,next_offset)`; `provider_snapshots(id,scan_id,symbol,retrieved_at,payload_json,sha256)`. SQL placeholders mandatory. RED→GREEN. Commit.
18. Add rollback/restart tests: failure between scan insert and cursor update rolls back both; repeated scan observation does not duplicate a trade; no-setup persisted; providerwidefailure cursor unchanged. Implement transactional save/cursor API. GREEN. Commit.
19. Add `tests/test_idx_outcomes.py` next-bar-open entry tests: observation09:35:02 cannot enter09:35 bar; first eligible09:40bar, entry deadline expired→unobservable; opening gap violates risk→entry rejected. Implement `advance_observation(...)` in `tradingagents/idx_strategies/outcomes.py` using immutable transitions. RED→GREEN. Commit.
20. Add stop/target both-touched→ambiguous, gapbelowstop→openreference, exact target-touch modeled-only, invalid/missing exit bar→unobservable. Implement chronological exits, exclude pre-entry bars. GREEN. Commit.
21. Add time exits across lunch and next-session morning, no overnight carry for day mode after missed deadline, future bars ignored. Apply costs only on observable reference paths; report ambiguous bounds separately. GREEN. Commit.
22. Add `tests/test_idx_strategy_evaluation.py`: incomplete observations excluded with counts, fees missing→net null, gross≠net, chronological holdout split, no candidate-specific tuning from evaluated outcomes. Implement summary in `tradingagents/idx_strategies/evaluation.py`. Labels must say hypothetical reference outcomes, not actual wallet profit. GREEN. Commit.

### Phase E — discovery and usable CLI

23. Add `tests/test_idx_strategy_rotation.py` registry70fake rows→25/25/20 rotation coverage, failed slot consumes budget but is recorded, restart resumes, request count<=25. Implement bounded selection in `tradingagents/idx_strategies/universe.py`; use `load_registry` directly. GREEN. Commit.
24. Add daily eligibility tests median turnover20, price floor, insufficient series, action ambiguity, no ticker guessed. Implement daily adapter/cache in `provider.py` separate from intraday raw bars. Cache key includes source/symbol/basis/interval/fetch time; no future daily values used in historical assessment. GREEN. Commit.
25. Add `tests/test_idx_strategy_cli.py` argparse tests for `python -m tradingagents.idx_strategies scan --strategy day|overnight|both --sessions PATH --db PATH --limit 25 --output PATH`; invalid/absent session file exits2 before requests, providerfail exits1 with partial artifact, no eligible setups exits0 with NO_SETUP count. Implement `cli.py` and `__main__.py`. Use dependency injection for clocks/provider tests. GREEN. Commit.
26. Implement human-readable output and full JSON export in `reporting.py` with tests: max3 cards; symbol, strategy, observation time/WIB, closed bar date, provisional vs observed entry, stop, 1.5R target, time exit, costs/coverage uncertainty, reasons. Never print green BUY for SETUP lacking an eligible future entry. Output labels `WATCH`, `SHADOW_ENTERED`, `NO_TRADE`; no auto-orders. GREEN. Commit.
27. Add `settle --sessions PATH --db PATH --output PATH` CLI tests and minimal implementation: fetch history for ALL pending symbols independently of current shortlist, apply outcome transitions, idempotent rerun. No scheduler installed. GREEN. Commit.
28. Add `evaluate --db PATH --output PATH` CLI tests and implementation: strategy-separated counts/outcomes, no pooled day/overnight win rate, no actual-PnL claims, missing/ambiguous coverage explicit. GREEN. Commit.

### Phase F — verification and delivery

29. Add sanitized authentic fixture excerpts from successful probe to `tests/fixtures/idx_intraday/` with `PROVENANCE.md` source, retrieval time, exact range, timezone, adjustment flags and license restrictions. Do not commit proprietary data without rights; if necessary retain fixtures locally and use synthetic tests in repo, disclose replay gap. Replay the identical input twice in separate processes into a temporary DB; expected identical assessments and no duplicate observations.
30. Run serial integrated suite on final source: `$PY -m pytest tests/ -q`; expected zero NEW failures, known optional Bedrock skip separately. Run `$PY -m ruff check tradingagents/idx_strategies tests/test_idx_*.py scripts/probe_idx_intraday.py` and `git diff --check`; expected clean. If existing tests match glob, do not mass-reformat unrelated files. Capture full logs outside repo.
31. Build wheel: `$PY -m pip wheel . --no-deps --no-build-isolation --wheel-dir /tmp/idx-strategy-wheel`. Inspect zip for new package modules; run installed-wheel CLI from a directory outside repo with an isolated target install. Expected `--help` works without API key/network. Do not assume editable-install success proves packaging.
32. Write `docs/IDX-STRATEGIES.md`: exact run commands, required session/calendar sourcing, strategy versions/defaults, fee/slippage input units, provider retention, raw-price basis, discovery coverage, explicit research-only boundaries. Include a `--dry-run` definition only if implemented; don't invent a flag. No automatic service installation.
33. Run ONE bounded live scan with official verified sessions, up to25symbols and no LLM, writing outside repo. Exact example after operator supplies sessions:

```sh
$PY -m tradingagents.idx_strategies scan \
  --strategy both --sessions /absolute/path/verified-idx-sessions.json \
  --db /tmp/idx-shadow.sqlite --limit 25 --output /tmp/idx-shadow-scan.json
$PY -m tradingagents.idx_strategies settle \
  --sessions /absolute/path/verified-idx-sessions.json \
  --db /tmp/idx-shadow.sqlite --output /tmp/idx-shadow-settlement.json
$PY -m tradingagents.idx_strategies evaluate \
  --db /tmp/idx-shadow.sqlite --output /tmp/idx-shadow-evaluation.json
```

Expected: parseable artifacts matching durable DB counts, exact source/request/valid/missing counts, at most3candidate cards, no orders/paid calls. Outside strategy window NO_SETUP is correct; do not alter clock or fixtures to force BUY. A same-day run cannot validate tomorrow's outcome; keep pending until a real eligible future session or report unobservable.
34. Obtain independent review of exact final diff, particularly no-lookahead, calendar correctness, and fill ambiguity; fix concrete blockers with new regression tests. Re-run final tests after any edits. Commit only reviewed source; never add `.env`, DBs, live logs or report artifacts blindly.
35. Push feature branch to `andri1-7/TradingAgents` and update existing PR only when execution is authorized. Read back exact remote SHA/PR contents and CI checks. Do not merge without user request. Final report must list implemented modes, actual scan coverage, statuses/outcomes, unresolved data limitations, verified tests and artifact paths. If live intraday data/calendar unavailable, say core implemented/offline verified and live operation blocked; do not claim full completion.

## Tests / validation checklist

- Per task: failing behavioral test → demonstrate exact expected failure → minimal implementation → targeted pass → commit. All synthetic fixtures labeled synthetic. No test may call paid API by default.
- Closed, aligned, coherent bars; no gap filling; raw price basis; corporate actions explicit.
- Calendar correct across Friday, lunch, holiday and next session; unknown calendar blocks admission.
- Signal timestamp <= actual observation time; future entry/open and future exit evidence only; no prior-bar execution.
- Stop/TP collision ambiguous, gap loss modeled at open; fees/slippage explicit and Decimal.
- Durable scans and all negative outcomes recorded; restart idempotence and cursor atomicity verified.
- Discovery rotation reaches every retained registry identity over scans; no silent top-N universe substitution.
- Per-strategy evaluation; unknown and ambiguous denominators reconciled programmatically.
- Live scan is operational proof only, NOT proof of predictive quality. Start prospective collection and require multiple distinct market regimes before choosing a strategy; no promised win rate or minimal sample count invented as statistical sufficiency.

## Risks, tradeoffs, and open questions

1. **Data availability is the primary gate.** Yahoo may have limited IDX 5m coverage/retention, delays and missing bars. A licensed provider may be necessary; seek approval before buying access or reusing another project's quota. Do not bypass restrictions.
2. **Broker details needed before net evaluation:** actual buy fee, sell fee/tax composition, slippage convention, board/auction behavior and settlement/buying-power constraints. No numeric fee defaults in production.
3. **Calendar source and maintenance:** obtain official current IDX sessions including holidays/Friday/auctions; no naive weekday scheduler. Source access could block delivery of a live-ready scanner.
4. **No executable-fill proof:** OHLC/volume cannot establish queue position, spreads, depth or partial fills. Backtests remain hypothetical and may overstate results.
5. **Lookahead and timestamp risk:** record receipt time, selection time and signal-bar end separately; a delayed fetch can invalidate a planned entry. Never use full-session VWAP/high/low at an earlier signal.
6. **Universe bias:** registry snapshot itself has an unresolved962vs963count discrepancy; partial25symbol scans are partial. Delisted/suspended symbols remain explicit error/status records, not quietly erased.
7. **Overnight events and gaps:** no promise that stops cap losses; corporate events/earnings calendar unknown initially. All shorts, leverage and execution remain out of scope.
8. **Risk budget/capital unspecified:** no position sizing or lot-based orders; user must supply these before adding execution-oriented recommendations.
9. **AI role deliberately deferred:** after deterministic baselines work, evaluate optional cached Sol/Jev annotations on identical cohorts with explicit request budgets. Never gate a retrospective subset on AI outcomes then claim rule profitability.
10. **Scope choice:** first deliver CLI/on-demand local shadow. Durable unattended scheduling, notifications and provider licenses are separate approvals, not hidden additions to this plan.

## Definition of done

Both strategies have deterministic tests, explicit policy/calendar/cost contracts, durable rotation and observations, honest outcome classification and documented CLI. Final full tests and independent review pass; a real bounded scan and read-back verify operation when provider/calendar prerequisites exist. No profitability claim, no hidden paid inference, no order execution, and no fabricated fill or current-complete coverage claim.
