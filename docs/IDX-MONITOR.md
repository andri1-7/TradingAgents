# Persistent IDX research monitor

Run directly, not through a Hermes scheduler:

```sh
python -m tradingagents.idx_strategies.monitor \
  --db /path/idx-shadow.sqlite --state-db /path/idx-monitor.sqlite \
  --output-dir /path/reports --interval 300 --ai-max-per-day 3 \
  --telegram-env /srv/alt-whale-tracker/.env --notify-startup
```

Add `--once` for one cycle. `--sessions PATH` overrides the packaged sourced calendar. Defaults: interval 300 seconds, AI maximum 3, packaged `assets/idx_sessions_2026.json`, existing tracker dotenv path above. Interval below 300 or AI cap outside 0–3 is rejected. The databases must be distinct. Parent owns service deployment; this module does not change crypto services, poll Telegram, register schedulers, place orders, or modify bot settings.

## Operation and coverage

- During exact supplied continuous-session intervals, call existing `cli.scan` with both strategies, Stockbit fee/slippage profile and 25 rotating registry slots. Existing scan persistence owns registry rotation; restarting the monitor preserves it. This is **25 ticker slots per rotation, not full-market real-time coverage**.
- Throttle scan and settlement starts durably to at least five minutes. Reservation happens before work, so crashes may skip one interval rather than hammer providers.
- Call existing `cli.settle` during the bounded live window from session open through close +30 minutes, including lunch and post-close. Overnight pending observations remain durable and resume on the next supplied session; there are no overnight/weekend polling fetches. Missing/out-of-coverage dates never trigger provider fetches. Packaged calendar currently ends November 6, 2026; it is not extrapolated. One durable per-chat calendar-health notification signals out-of-coverage idle state.
- Process only SETUP assessments, at most the first three candidate keys per scan, with at most **one analysis run per cycle**. Cached keys are skipped before choosing the next eligible key. The default analyzer is late-imported `ai_runner.run_analysis(candidate)` (runner default timeout 180 seconds, owned by another module). AI is serial and can delay ingestion/rotation; this is not a separate uninterrupted ingestion worker.
- Atomic SQLite reservations are unique by `(symbol, strategy, session_date, rubric_version)` and count against the Jakarta reservation date. Failed and crashed reservations consume the cap; they are never automatically recharged or retried. **Three/day means three analysis runs, not three provider API requests or a dollar ceiling.** A full run may call several models/APIs. Keep a single state database across restarts and workers; deleting it resets the protective ledger.
- After analysis, check the original entry deadline and call `revalidation.revalidate_candidate(candidate, calendar, clock=clock)` on the exact ticker. Accept only a valid matching symbol/strategy assessment completed before the original deadline. Fresh verified results become `WATCH_REVALIDATED`; absent/failed/unverified/late results become `EXPIRED`. Both remain `actionable=false`; AI never overrides rule eligibility or produces an executable BUY. No discovery scan is used for revalidation, so this does not advance registry rotation.

## Delivery and durability

`--notify-startup` enables Telegram delivery and sends a startup notification once per configured chat **for the lifetime of this state database**, not per process restart. Telegram credentials and authorized recipients are read by `telegram_delivery.telegram_config(path)` only. Other notices are one per completed candidate analysis before its original deadline, a close+30-minute daily summary, and the calendar-health notice: never per-scan spam. Analyses completing after the deadline are persisted EXPIRED and omitted from immediate delivery; the daily summary still records their supporting views. Summary cards are capped at three, with real persisted scan/provider/settlement/runtime and AI reservation/error counts. Full raw analysis remains in SQLite; rendered Sol and Jev supporting views are separate, bounded and explicitly expired/unavailable where appropriate.

Outbox primary key is `(event, chat)`. Failed sends remain pending for later cycles, with error classes only, no exception messages. Successful sends retain a JSON `receipt` containing exact target `chat_id`, `sent_at`, and the actual sender response, including Telegram's message ID. Existing outbox databases gain the receipt column automatically. Negative `ok` acknowledgments are rejected. Local acceptance tests use injected senders, not real Telegram messages.

Telegram lacks idempotency keys: if Telegram accepts a send and the process crashes before the SQLite receipt transaction commits, retry may duplicate that message. This is durable per-chat deduplication, **not exactly-once delivery**. Do not delete sent outbox rows or reset the database to resend startup. A no-return injected sender is allowed for offline tests; the production wrapper requires a positive validated `send_text` receipt.

## Injection/API contract

```python
run_cycle(args, calendar, *, scanner=None, settler=None, analyzer=None,
          sender=None, clock=None, chats=(), revalidator=None) -> dict
```

- `args`: `db`, `state_db`, `output_dir`, `interval=300`, `ai_max_per_day=3`, `notify_startup=False`.
- `scanner(args, calendar, clock=clock)` / `settler(...)`: return a report dictionary, or existing CLI integer result with report written to `args.output`. Generated namespaces carry `limit=25`, `strategy='both'`, `cost_profile='stockbit'` and all four manual cost overrides set to `None`.
- `analyzer(candidate) -> dict`; default late imports runner. Runner owns provider credentials and process timeouts.
- `revalidator(candidate, calendar, clock=clock) -> {'valid': bool, 'assessment': dict, 'checked_at': timestamp, ...}`; missing/error fails closed.
- `sender(chat_id: int, payload: dict) -> receipt`; return `False` or dictionary without `ok=True` is failure. Production uses `send_text(text, token, chat_id)` and `format_support(candidate, normalized_analysis)` with independent Sol/Jev views. Callback exceptions persist only their class.
- `clock() -> aware datetime`.
- Result has `status`, `analyzed`, and safe error-class list. Continuous main prints flushed JSON cycle results and safe exception classes; `--once` exits after one cycle. Calendar outage idles rather than inducing a restart loop.

Offline verification: `python -m pytest tests/test_idx_monitor.py -q`. No paid provider calls, deployment, or real Telegram sends are part of these tests.

## Deployment evidence and limitations (2026-10-28)

The separate `idx-stockbit-monitor.service` uses the shared alt-whale bot in send-only mode. Startup receipt is stored in the local outbox; no crypto services are restarted. Activation happened after continuous trading closed, so initial real cycles are CLOSED; a future market-open scan and real qualifying candidate delivery are not yet proven.

The final bounded AI adapter control run exceeded its 180-second process deadline and returned `analysis_timeout`. An earlier adapter snapshot completed an AADI NO_SETUP control with Sol Hold / Jev HOLD, but that earlier run does not validate the final previous-session cutoff version. Do not describe the final AI path as live-proven successful. Failed analyses remain FAILED and consume their reservation. Daily graph data/news use the previous verified session, while the scanner's current closed-5m evidence is separately injected; this is not live same-day news coverage.

Outputs are read only after a fresh invocation removes the prior artifact. Pending analysis messages are downgraded to EXPIRED at delivery after their deadline. Daily summaries use compact max-three model views to stay within Telegram limits. Telegram receipts prove API acceptance, not that the user read the message.

Calendar coverage ends 2026-11-06. Coverage is only 25 rotating ticker slots per cycle, especially limited in the five-minute overnight window. AI can delay the next scan; no full-universe simultaneous monitoring is claimed.
