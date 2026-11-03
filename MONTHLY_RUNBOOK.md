# Monthly rebalance runbook

Do this in the first week of each month (a trading weekday, ideally 09:30-14:30 IST). About 15 minutes.

## A. Research machine (HPC) - make the new signal
```
ssh hpc
cd ~/daily_automation_testing/files
python refresh_prices.py price_cache/nifty500_daily.parquet <FIRST DAY OF THIS MONTH, YYYY-MM-DD>
cd <the Trading_strategy folder on the HPC>
python scripts/export_from_research.py \
  --research-dir ~/daily_automation_testing/files \
  --prices ~/daily_automation_testing/files/price_cache/nifty500_daily.parquet \
  --members ~/daily_automation_testing/files/nifty500_membership.csv \
  --output-dir ~/daily_automation_testing/files/artifacts \
  --membership-kind official
```
Check the output says `official` and the signal date is the last trading day of last month.

## B. Mac - fetch the signal
```
cd ~/Documents/kite/Trading_strategy
scp hpc:~/daily_automation_testing/files/artifacts/* artifacts/
```
(4 files: signals_momentum.csv, signals_ridge.csv, ridge_model.json, manifest.json.)

## C. Mac - run the bot (one command)
```
scripts/monthly.sh
```
It asks LIVE or dry run, logs you into Kite, runs `scripts/preflight.py`, then:
1. **Sells** names that left the top-45 rank buffer (full exits, never trims names still selected).
2. Waits for you to confirm the sells filled.
3. **Buys** within your free cash (`--fit-cash`), capped at 20% turnover (`BUY_TURNOVER` to change).

Every step shows your live Kite portfolio and the plan, then asks `y / s / n` before placing anything.
Do a dry run first (just type anything but LIVE).

Resume or split steps: `scripts/monthly.sh sells` / `scripts/monthly.sh buys`.

## D. Afterwards
- `.venv/bin/python scripts/order_status.py` - 'submitted' is not 'filled'. Unfilled DAY orders expire at the close.
- Nothing else: all holdings are bot-managed (`MANAGE_ALL_HOLDINGS=YES` in `.env`), so no `mark_managed.py`.

## Things that go wrong
| Message | Fix |
|---|---|
| `IP (...) is not allowed to place orders` | Add the IP printed by `preflight.py` to the Kite developer console. |
| `shares need to be authorised at CDSL` | Kite > Holdings > Authorise (TPIN/OTP), then `scripts/monthly.sh sells`. |
| `TokenException` / login errors | `.venv/bin/python scripts/auth_kite.py` (tokens expire ~07:30 IST daily). |
| `exceed available cash` | Add funds or wait for sale proceeds; buys step sizes itself to free cash. |
| `already submitted` | That phase already ran for this signal date. Check `order_status.py`. `--force` only after checking. |
| `NSE looks closed` | Run 09:15-15:30 IST on a trading day. |
| 3 failed orders in a row | The run stops by design; fix the cause above and re-run. |

## Switches (set in `.env`, or env vars on the command line)
`EXECUTION_MODE`, `STRATEGY_CAPITAL`, `MANAGE_ALL_HOLDINGS`, `MAX_TURNOVER`, `MAX_WEIGHT`, `FIT_CASH`, `EXITS_ONLY`, `PHASE`, `FORCE`.
