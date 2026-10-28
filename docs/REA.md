# REA investigation notes

## Scope
User requested https://rea.tools/guides/ while extending TauricResearch/TradingAgents for Indonesian stocks. Read guides and Get Started in browser. REA is a reverse-engineering toolkit, not a financial data provider. TradingAgents is open-source Python, so source-level inspection and behavioral tests are primary; bytecode inventory does not verify financial correctness.

## Verified commands
Host Node was v22.23.1, below REA 6.8.0's supported minimum. Used an isolated npm-exec Node 22.23.4, without replacing the host runtime:

```sh
npm exec --yes --package=node@22.23.4 --package=rea-agents@6.8.0 -- rea --help
npm exec --yes --package=node@22.23.4 --package=rea-agents@6.8.0 -- rea doctor --json
python3 -m py_compile tradingagents/dataflows/symbols.py
npm exec --yes --package=node@22.23.4 --package=rea-agents@6.8.0 -- rea inspect-python-pyc tradingagents/dataflows/__pycache__/symbols.cpython-311.pyc --detail summary --evidence_output /root/projects/TradingAgents-rea-symbols-evidence --format json
```

REA successfully inventoried the upstream symbol-normalization module's CPython 3.11 artifact: five code objects; complete coverage under its bounds. Evidence bundle: `/root/projects/TradingAgents-rea-symbols-evidence`.

`doctor` returned healthy=false: optional native analysis engines and agent MCP registrations are absent. CLI bytecode inspection succeeded independently. No global Hermes configuration or MCP registration was changed, no native analysis engines were installed, and full REA integration is not claimed.

Limitations: REA retains bytecode lengths/digests in this workflow; it does not decompile or recover source. The inventory is not evidence of IDX price availability, backtest accuracy, or profitable recommendations.
