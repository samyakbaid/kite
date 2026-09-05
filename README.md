# Ridge + Momentum deployment for Kite

This repository is the small deployment half of the walk-forward research project. It
does not contain the 35 MB price cache, training logs, TFT code, or backtest outputs.
Instead, it contains:

- dated Ridge and 12-1 momentum rankings (about 35 KB each);
- the latest fitted Ridge coefficients and feature scaling (about 1 KB);
- a guarded local Kite rebalancer; and
- a research-side exporter for producing the next month's artifacts.

The backtest that produced these defaults used 30 equal-weight holdings, a 50% rank
buffer, a 20% one-way monthly turnover cap, 8 bps slippage, and Ridge lambda 25. Over
February 2011–August 2026, estimated net Sharpe was 0.98 for momentum and 0.88 for
Ridge. These are research estimates, not expected returns.

## Important data warning

The included August 31, 2026 signals use the repository's **liquidity-proxy universe**,
not official historical Nifty 500 constituents. Some selected names are small and may
have material liquidity/slippage risk. Live execution from these artifacts is blocked
unless you explicitly override the block. The correct next data step is replacing the
membership file with official point-in-time snapshots and re-exporting with
`--membership-kind official`.

## Mathematics & Strategy Methodology

The rebalancer uses an **Equal-Weight Momentum Strategy** combined with **Ridge Regression** signals.

### 1. Position Sizing (Equal-Weighting)

The target for each selected asset is to be equally weighted based on the total strategy capital.
For a given strategy capital ($C$) and number of target holdings ($N$):

- **Target Capital per Stock** = $C \div N$

For our defaults (Capital = ₹1,00,000, $N$ = 30):
Target Capital = $100,000 \div 30 \approx 3,333$ INR

The actual quantity to buy is always rounded down to the nearest whole share (floor function) to ensure we don't exceed the allocated capital per asset:
- **Quantity to Buy** = $\lfloor \text{Target Capital} \div \text{Last Traded Price (LTP)} \rfloor$

If you already hold shares of a target asset, the quantity to buy is adjusted:
- **Quantity to Buy** = $\lfloor \text{Target Capital} \div \text{LTP} \rfloor - \text{Current Holding Quantity}$

### 2. Monthly Turnover Cap

To minimize slippage and trading costs, the backtest and live execution enforce a **20% one-way monthly turnover cap**.
- **Max Allowed Trading Value** = $C \times 0.20$

This means a new portfolio scales into its target positions over roughly 5 months (20% per month) rather than executing 100% turnover immediately. Sells are executed first, and the proceeds are re-allocated to buys.

### 3. Bootstrap Mode (Initial Deployment)

For the very first deployment, `BOOTSTRAP` mode can be enabled. This temporarily bypasses the 20% turnover cap and sets it to 100%, allowing the portfolio to be fully invested in a single run.
After the initial buys, a **Residual Top-up Pass** deploys leftover cash (from the integer share rounding) into the highest-ranked names, one additional share at a time, until the maximum per-asset weight (default 10%) or total capital is reached.

## Local setup

```bash
git clone https://github.com/samyakbaid/Trading_strategy.git
cd Trading_strategy
python3 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env
chmod 600 .env
```

Put your existing Kite API key and current access token in `.env`. `.env`, local state,
and order receipts are ignored by Git. Never put the API secret, request token, access
token, or account data in a signal artifact.

Start with:

```dotenv
KITE_API_KEY=...
KITE_ACCESS_TOKEN=...
KITE_LIVE_TRADING=DISABLED
STRATEGY_MODEL=momentum
STRATEGY_CAPITAL=100000
EXECUTION_MODE=dry_run
ALLOW_PROXY_UNIVERSE=NO
```

Run a dry plan:

```bash
./scripts/run_local_rebalance.sh
```

The script pulls the newest committed signal artifact, reads live holdings and LTPs,
and writes a receipt under `receipts/`. It does not submit an order in dry-run mode.

## Safety model

The rebalancer is deliberately fail-closed:

- CNC, NSE, long-only orders;
- LIMIT orders by default, priced within a configurable buffer around LTP;
- hard capital, turnover, per-order value, order-count, signal-age, and cash checks;
- sells before buys and skips buys if a sell submission errors;
- signal SHA-256 verification when `manifest.json` is present;
- one live submission per model/signal date unless `--force` is explicitly supplied;
- no sale of holdings outside `.trading_state/<model>.json`; and
- proxy-universe, live-mode, and confirmation gates.

Kite returning an order ID means the order was submitted, not filled. Always inspect the
Kite order book and saved receipt. A delivery sell can also require your account's normal
DDPI/TPIN authorization. Do not manually trade symbols managed by this bot: holdings do
not identify which shares came from which strategy. A separate strategy account is the
cleanest setup.

The 20% turnover cap also means a new portfolio ramps toward its target over several
monthly runs. This matches the backtest rather than investing 100% immediately.

## First deployment (bootstrap)

To get fully invested in one run instead of ramping in over five months, use bootstrap
mode. It lifts the turnover cap to 100% for that single run; every later run reverts to
the standard `--max-turnover` cap.

- The rebalancer **auto-enables** bootstrap when the model has no recorded submissions
  and no managed holdings. Pass `--no-bootstrap` (or `BOOTSTRAP=NO`) to opt out.
- To force it on a model that already has a submission (e.g. reconciling a partial
  fill), run `BOOTSTRAP=YES FORCE=YES ./scripts/run_local_rebalance.sh` after checking
  the saved receipt and the Kite order book. `--force` re-submits every planned order,
  so only use it once you know what is already filled.

A residual top-up pass then spends left-over cash (integer-share rounding, and names
priced above the equal-weight budget of `capital / n_hold`) on extra whole shares of the
highest-ranked names, one at a time, until the turnover budget, the per-order value cap,
available cash, or the `--max-weight` per-name ceiling (default 10%) is reached. Disable
it with `--no-top-up`. The top-up always stays inside `--max-turnover`, so on normal
monthly runs it only mops up rounding crumbs; on a bootstrap run it fills the book.

Names priced above `--max-weight * capital` are still skipped rather than held at an
outsized weight. With `STRATEGY_CAPITAL=100000` and 30 holdings the equal-weight budget
is only about ₹3,333 per name, so raising capital is the real fix for broad coverage.

## Enabling live mode

First review multiple dry-run receipts. Live mode requires all of these:

```dotenv
EXECUTION_MODE=live
KITE_LIVE_TRADING=ENABLED
```

Official-universe artifacts then run normally. The current proxy artifacts additionally
require the following explicit acknowledgement, which is not recommended:

```dotenv
ALLOW_PROXY_UNIVERSE=YES_I_ACCEPT_PROXY_RISK
```

For a sell-first two-stage rebalance, call the CLI directly with `--phase sells`, verify
the fills, then use `--phase buys`. Direct CLI help is available with:

```bash
.venv/bin/trading-rebalance --help
```

## Monthly automation

Your Kite access token must be valid before the scheduled process starts. A sample cron
entry that attempts the job on weekday mornings during the first seven days of each
month is:

```cron
35 9 1-7 * * test "$(date +\%u)" -le 5 && cd /absolute/path/Trading_strategy && ./scripts/run_local_rebalance.sh >> rebalance.log 2>&1
```

The local state makes repeat live attempts for the same signal date fail. Use `--force`
only after reconciling the saved receipt with Kite's order book.

## Publishing a new monthly signal

Run this on the research machine, not the Kite machine:

```bash
.venv/bin/python scripts/export_from_research.py \
  --research-dir /path/to/daily_automation_testing/files \
  --prices /path/to/nifty500_daily.parquet \
  --members /path/to/nifty500_membership.csv \
  --output-dir artifacts \
  --membership-kind official
```

Review `artifacts/manifest.json` and the top-ranked names, then commit and push the four
small artifact files. The local machine receives them on its next `git pull`.

## Development checks

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Kite integration follows Zerodha's [official Python client](https://github.com/zerodha/pykiteconnect)
and [Kite Connect v3 order API](https://kite.trade/docs/connect/v3/orders/). Keep the
client updated and test changes in dry-run or [Kite's sandbox](https://kite.trade/docs/connect/v3/sandbox/)
before using real funds.
