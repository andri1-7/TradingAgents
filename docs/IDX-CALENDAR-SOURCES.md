# IDX calendar source evidence — bounded 2026 research slice

## Artifact and scope

- Artifact: `tradingagents/assets/idx_sessions_2026.json`, compatible with `tradingagents.idx_strategies.sessions.load_sessions`.
- Retrieved/reviewed via `web_extract` on **2026-10-28T06:20:36+00:00** (UTC; compilation timestamp after the source fetches).
- Inclusive coverage: **2026-09-01 through 2026-11-06**, **49 sessions**: September 22, October 22, November 2–6 five. The filename is not a full-year claim.
- Actual machine clock confirmed 2026-10-28 in Asia/Jakarta. There are **41 dated sessions before October 28**, the current October 28 session, and **seven future sessions**: October 29–30 and November 2–6. Before-today sessions are completed by calendar time, not proof that every scheduled minute actually traded. At initial clock check, October 28 was 13:18 Jakarta and was not complete.
- This is official-source-derived **research data**, not an operator approval or exchange certification of this JSON. No live configuration, orders, paid AI, or application code was changed.

## Official holiday evidence

Requested PDF URL (primary `source_url`):

https://www.idx.co.id/StaticData/NewsAndAnnouncement/ANNOUNCEMENTSTOCK/Exchange/Peng-00171%20Libur%20Bursa%202026-No.%20Peng-00171BEI.POP09-2025.pdf

Full-body successful extraction URL (same official document, non-www host):

https://idx.co.id/StaticData/NewsAndAnnouncement/ANNOUNCEMENTSTOCK/Exchange/Peng-00171%20Libur%20Bursa%202026-No.%20Peng-00171BEI.POP09-2025.pdf

Document identity: **PENGUMUMAN Kalender Libur Bursa Tahun 2026**, **No. Peng-00171/BEI.POP/09-2025**, dated **23 September 2025**. The appendix contains both Indonesian and English calendars. Exact relevant rows:

| Month | Official remarks | Full-month trading days |
| --- | --- | --- |
| September | No trading holidays except for Saturday and Sunday | 22 |
| October | No trading holidays except for Saturday and Sunday | 22 |
| November | No trading holidays except for Saturday and Sunday | 21 |

Indonesian wording: “Tidak ada hari libur kecuali Sabtu dan Minggu”. Only after verifying these explicit rows were weekdays enumerated for the bounded slice. Weekend exclusions are therefore supported by the official holiday appendix, not a weekday-only calendar guess. No weekday holiday lies in this slice under the announcement.

Extraction caveat: the www request returned a shortened body ending in the September row despite a generous requested character budget. A second `web_extract` request to the official non-www PDF returned the complete three-page body, including all three relevant rows and both appendices. Its result metadata reported `https://idx.co.id/id` with an empty title; the extracted body unambiguously identifies the PDF announcement number, date, appendix, and calendar. Preserve the requested PDF URL rather than treating that metadata URL as the source document. This is extracted-text provenance, not a downloaded-PDF hash or signed-document authenticity check.

The announcement explicitly permits later changes if Bank Indonesia closes clearing or the government declares another public holiday. The base PDF is not evidence that no later halt or amendment exists.

## Actual official hours retrieved

https://www.idx.co.id/en/products-services/trading-hours-and-mechanism/

Also successfully extracted without the trailing slash and at the official non-www host. The current page cites **Kep-00158/BEI/10-2026**, not the older 2024 rule mentioned in prior research. Exact regular-market continuous sessions:

| Days | Session I | Session II |
| --- | --- | --- |
| Monday–Thursday | 09:00:00–12:00:00 | 13:30:00–15:49:59 |
| Friday | 09:00:00–11:30:00 | 14:00:00–15:49:59 |

Times are JATS/WIB; the artifact encodes aware `+07:00` timestamps and `Asia/Jakarta`.

Current signed rule PDF retrieved:

https://www.idx.co.id/Media/stumk2gi/signed_peraturan_nomor_ii_a_tentang_perdagangan_efek_bersifat_ekuitas-261020.pdf

Identity: **Kep-00158/BEI/10-2026**, issued/effective **20 October 2026**. Sections **IV.2.1.2–IV.2.1.3** and **IV.2.2.2–IV.2.2.3** explicitly state the four continuous-auction intervals above. It supersedes Kep-00157/BEI/10-2026 dated 19 October 2026; the decision describes auto-rejection changes.

Earlier signed rule PDF retrieved:

https://www.idx.co.id/Media/bgqhucr0/signed_perubahan_peraturan_nomor-_ii_a__tentang_perdagangan_efek_bersifat_ekuitas.pdf

Identity: **Kep-00136/BEI/09-2026**, issued **21 September 2026**, effective **28 September 2026**. Its appendix identifies the prior **Kep-00003/BEI/04-2025** dated/effective **8 April 2025**, amended by this decision. It contains the same four IV.2 continuous-auction clauses and hours. This corroborates the schedule before the latest October rule; it is not a separately retrieved original April 2025 version or a complete historical rule-change audit for September 1–27 or October 19. The uniform base hours across the bounded slice use this consistent official rule/page evidence; that historical limitation remains explicit.

### Half-open 5-minute encoding

`load_sessions` requires Jakarta-local, second-zero, five-minute-aligned interval endpoints. Encode regular intervals as `[09:00,12:00)` / `[13:30,15:50)` Monday–Thursday, and `[09:00,11:30)` / `[14:00,15:50)` Friday. The afternoon exclusive endpoint **15:50:00** represents the official continuous session ending **15:49:59**, not inclusion of preclosing. Morning close is retained as the official 12:00/11:30 boundary for complete bars; no extra second is added.

Preopening is excluded; preclosing input starts 15:50; matching 16:00–16:01:59 and postclosing 16:02–16:15 are excluded. Cash-market, negotiated-market, derivatives, and Watchlist Full Call Auction schedules are not encoded. The general calendar does not establish any security's board eligibility, suspension status, liquidity, or provider bar-label convention.

## Known actual halt: October 16 is conservatively adjusted

https://www.idx.co.id/en/news/press-release/2724

Successfully extracted official **PR No. 093/BEI.SPR/10-2026**, dated **16 October 2026**, “Trading Halt Due to Decline in IHSG”. Relevant exact statement:

> Today, Friday, 16 October 2026 there has been a halt on the trading system ... at 08:58:00 ... The trading will resume at 09:28:00 JATS time without any change in trading schedule.

The October 16 JSON morning interval starts **09:30**, not 09:00 or 09:28: the announced halt overlaps regular continuous trading, and the loader cannot represent a 09:28 boundary. Rounding the usable opening forward excludes the partial 09:25–09:30 bar and two minutes after announced resumption. This is an explicitly conservative complete-bar research adjustment, not a claim that the exchange reopened at 09:30. The afternoon remains 14:00–15:50 exclusive. No other actual halts are inferred absent evidence; the artifact is **not an exhaustive actual-halt log**.

## Amendment and interruption search

Searches executed on 2026-10-28 UTC:

- `site:idx.co.id 2026 "Perubahan" "Libur Bursa"`
- `site:idx.co.id "2026" "Penyesuaian" "Kalender Libur Bursa"`
- `site:idx.co.id "2026" "September" "libur" "Bursa"`
- `site:idx.co.id "2026" "Oktober" "libur bursa"`
- `site:idx.co.id "2026" "November" "libur bursa"`
- `site:idx.co.id "Kep-00158/BEI/10-2026"`
- `site:idx.co.id "Kep-00196/BEI/12-2024"`
- `site:idx.co.id "II-A" "2024" "signed"`
- `site:idx.co.id "Kep-00139" "II-A"`
- `site:idx.co.id "Kep-00157/BEI/10-2026"`
- `site:idx.co.id/en/news/press-release "2026" "Trading Halt" "Sep"`
- `site:idx.co.id/en/news/press-release "2026" "Trading Halt" "Oct"`
- `site:idx.co.id "Kep-00003/BEI/04-2025" "pdf"`
- `site:idx.co.id "Kep-00157/BEI/10-2026" "pdf"`

A prominent apparent amendment hit was fetched in full:

https://www.idx.co.id/StaticData/NewsAndAnnouncement/ANNOUNCEMENTSTOCK/Exchange/Penyesuaian%20Kalender%20Bursa%20Peng-00171%20ID-No.%20Peng-00171BEI.POP09-2026.pdf

It is **Peng-00171/BEI.POP/09-2026**, dated **17 September 2026**, correcting wording for the **2027** calendar, expressly not changing that calendar's dates. It is **not** a 2026-calendar amendment; the similar announcement number must not be conflated with the September 2025 announcement for 2026. Other results included 2027 calendars and issuer-specific suspensions/warrant adjustments, not a verified change to this slice's holiday dates. The October 16 halt above was found during the rule search and retained rather than silently ignored.

No holiday-date amendment affecting September 1–November 6, 2026 was identified in these indexed searches. This is **not proof of absence**: indexed search is incomplete; ad-hoc exchange-wide halts, security-specific suspensions, later notices, and future changes may exist. Recheck official notices before operational use. The attempted old Indonesian hours URL `/id/produk-dan-layanan/jam-perdagangan/` was denied; the official English page and rule PDFs succeeded without bypassing access controls.

## Validation

Validation uses the repository's actual `load_sessions`, not a replacement parser. Acceptance checks: 49 unique sorted sessions, inclusive bounds, exact official-appendix-derived dates, both full-month September/October counts, at least 21 prior completed dated sessions (41 available), October 28 present, October 29 next, seven subsequent dates, correct Friday/non-Friday intervals, explicit October 16 conservative exception, five-minute-aware Jakarta boundaries, policy windows, missing weekends and fail-closed next-session lookup after November 6. Existing `tests/test_idx_sessions.py` tests synthetic validation behavior, not source authenticity. Executed with `/root/projects/TradingAgents/.venv/bin/python`: direct `load_sessions` assertions passed for all 49 rows and 48 overnight pairs; 41 prior completed dated sessions were confirmed, with latest-21 range 2026-09-29 through 2026-10-27. `python -m pytest -q -p no:cacheprovider tests/test_idx_sessions.py` returned **12 passed in 3.03s**. These checks establish parser/policy compatibility, not source authenticity or operator sign-off.
