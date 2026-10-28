# IDX intraday and overnight shadow research

Research only: no orders, scheduler, paid models, or profitability claims.

## Commands

From repository root, with Python >=3.11 and installed project dependencies:

```sh
python -m tradingagents.idx_strategies --help
python -m tradingagents.idx_strategies scan --strategy both --sessions /path/verified-sessions.json --db /path/shadow.sqlite --limit 25 --output /path/scan.json
python -m tradingagents.idx_strategies settle --sessions /path/verified-sessions.json --db /path/shadow.sqlite --output /path/settle.json
python -m tradingagents.idx_strategies evaluate --db /path/shadow.sqlite --output /path/evaluation.json
```

Calendar is mandatory. Supply `source_url`, aware ISO `retrieved_at`, `timezone: Asia/Jakarta`, and `sessions` containing `{date: YYYY-MM-DD, intervals: [[aware_open, aware_close], ...]}`. Intervals are continuous trading only, excluding auctions/lunch. Include at least the preceding21 actual sessions for daily freshness/coverage, the current session and next session for overnight. No weekday-generated production calendar. A changed calendar fingerprint blocks settlement of admitted observations; preserve original file for pending trades. A sourced bounded calendar is packaged at `tradingagents/assets/idx_sessions_2026.json`; see `docs/IDX-CALENDAR-SOURCES.md` for its exact coverage and evidence. This is a dated schedule snapshot, not a live halt/suspension feed. Out-of-coverage dates still fail closed.

Supply all four explicit decimal-fraction cost flags to admit research setups:

```sh
--buy-fee YOUR_FRACTION --sell-fee YOUR_FRACTION --buy-slippage YOUR_FRACTION --sell-slippage YOUR_FRACTION
```

Alternatively, explicitly select `--cost-profile stockbit`: buy fee **0.15%**, sell fee **0.25%**, plus **0.10% slippage per side** as an unmeasured research assumption, NOT a Stockbit fee or guaranteed execution bound. Profile source/assumptions persist in artifacts and observations. Do not combine the profile with manual overrides; use all four manual flags for a different scenario. No profile is silently enabled. Missing costs prevent SETUP. Meterai (Rp10,000 on qualifying daily trade confirmations) and datafeed costs are excluded because the return model has no portfolio notional/day-level allocation; reported net is after modeled proportional costs only, not all-in actual PnL.

```sh
python -m tradingagents.idx_strategies scan \
  --sessions tradingagents/assets/idx_sessions_2026.json \
  --cost-profile stockbit --strategy both --limit 3 \
  --db /path/stockbit-shadow.sqlite --output /path/stockbit-scan.json
```

Monetary values use Decimal strings. Net outcomes remain hypothetical reference returns, never actual portfolio PnL.

## Policies v1

- `day`: first30minutes opening range, later breakout then latest closed retest, aboveVWAP, preceding20bar relative volume >=1.5; finish15minutes before continuous close.
- `overnight`: assess30minutes before continuous close within5minute window, above previous completed dailyEMA20 and VWAP, top25% session-to-date close location, relativevolume>=1.5, <=2% EMA extension. Next-session morning time exit30minutes after continuous open.
- Shared: prior20median raw close×volume proxy>=IDR10bn, raw close>=100, valid closed5minute bars, no known corporate-action ambiguity, reference stop distance<=2%. Cost-adjusted target solves net reward/risk1.5; this is a policy target, not evidence price will reach it. The gross1.5R reference is retained separately.
- Defaults are research assumptions, not optimized or validated trading edges. Current thresholds live in rules.py/cli.py; do not silently tune them after inspecting outcomes.
- Entry is the exact first future eligible5minute bar open after durable observation. Missing entry slot is unobservable, not replaced with a later favorable price. A delayed persistence crossing a boundary rejects admission conservatively.
- Stop/target touches are modeled references, not fills; both within one candle is ambiguous. Gap stops use opening reference. Calendar membership is required for outcome bars. Prospective collection must continue into future sessions; one scan cannot prove tomorrow's return.

## Coverage and persistence

Registry rotation sorted by symbol, up to25ticker slots per scan, serial requests (concurrency1, within cap2). Each slot may make two history requests (intraday/daily); no automatic retries. Failed symbols remain recorded. Entire-provider failure preserves cursor. No top-volume-only universe substitution. Rotation cursor and evidence records commit together; actionable observations use conservative subsequent admission.

SQLite retains scans, all assessments including negatives, hashed provider snapshots, rotation and observations. Payload columns preserve extensible evidence, timestamps and Decimal strings. Run `settle` explicitly: it examines all pending observations independently of current rotation. A transient provider failure leaves pending rows retryable. Duplicate scans cannot duplicate a same-symbol/strategy/session/rubric observation.

Artifacts contain max3unique WATCH/SHADOW_ENTERED cards and the full assessment list. WATCH is NOT BUY. No eligible cards is valid. Evaluation separates strategies; ambiguous/missing outcomes and unknown net costs remain explicit. Chronological cohorts are a research split, not proof of statistical sufficiency or freedom from all selection bias.

## Provider and live evidence

Yahoo5m adapter uses raw prices (`auto_adjust=False`) and actions, explicit aware bounds and closed bars only; vendor failures are categorized without exception text. No persistent provider cache was added: each saved provider envelope carries its receipt time. Probe actual retention using `scripts/probe_idx_intraday.py`; library support is not a retention guarantee. Missing bars are not filled. Illiquid/suspended names may be unavailable, and empty history does not prove suspension.

A bounded3ticker live scan on2026-10-28 recorded two valid histories and one provider error, no entries. Settlement/evaluation ran with zero pending outcomes; no profit or win rate is claimed. This is partial operational evidence, not full962issuer monitoring. The follow-up Stockbit configuration supplies the standard proportional fees and explicitly assumed slippage, with a sourced 49-session bounded calendar. A new three-ticker live scan still recorded two valid histories, one provider error, and no setup outside the decision window. This does not establish signal profitability or all-in account costs.

## Verification

```sh
python -m pytest tests/test_idx_shadow_foundations.py tests/test_idx_intraday_provider.py tests/test_idx_sessions.py tests/test_idx_features.py tests/test_idx_day_rules.py tests/test_idx_overnight_rules.py tests/test_idx_strategy_ranking.py tests/test_idx_strategy_store.py tests/test_idx_outcomes.py tests/test_idx_shadow_cli.py tests/test_idx_shadow_integration.py -q
python -m pytest tests/ -q
```

All test calendars and market fixtures are synthetic unless explicitly marked otherwise. No hidden model inference. Never commit `.env`, live SQLite files or provider datasets without checking rights.
