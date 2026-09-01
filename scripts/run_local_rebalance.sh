#!/usr/bin/env bash
set -euo pipefail

REPO_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_DIR"

if [[ ! -d .venv ]]; then
  echo "Missing .venv. Run: python3 -m venv .venv && .venv/bin/pip install -e ." >&2
  exit 2
fi
if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi
: "${STRATEGY_CAPITAL:?Set STRATEGY_CAPITAL in .env or the environment}"

STRATEGY_MODEL=${STRATEGY_MODEL:-momentum}
EXECUTION_MODE=${EXECUTION_MODE:-dry_run}
case "$STRATEGY_MODEL" in
  momentum) SIGNAL_FILE="artifacts/signals_momentum.csv" ;;
  ridge) SIGNAL_FILE="artifacts/signals_ridge.csv" ;;
  *) echo "STRATEGY_MODEL must be momentum or ridge" >&2; exit 2 ;;
esac

# Pull only code/artifacts. Local credentials, receipts, and state are ignored by Git.
git pull --ff-only

LIVE_ARGS=()
PROXY_ARGS=()
if [[ "$EXECUTION_MODE" == "live" ]]; then
  LIVE_ARGS=(--live --confirm-live PLACE_ORDERS)
elif [[ "$EXECUTION_MODE" != "dry_run" ]]; then
  echo "EXECUTION_MODE must be dry_run or live" >&2
  exit 2
fi
if [[ "${ALLOW_PROXY_UNIVERSE:-NO}" == "YES_I_ACCEPT_PROXY_RISK" ]]; then
  PROXY_ARGS=(--allow-proxy-universe)
fi

mkdir -p .trading_state receipts
exec 9>".trading_state/${STRATEGY_MODEL}.lock"
if ! flock -n 9; then
  echo "Another rebalance is already running for ${STRATEGY_MODEL}" >&2
  exit 3
fi

.venv/bin/trading-rebalance \
  --signals "$SIGNAL_FILE" \
  --capital "$STRATEGY_CAPITAL" \
  --state-file ".trading_state/${STRATEGY_MODEL}.json" \
  --receipt-dir receipts \
  "${PROXY_ARGS[@]}" \
  "${LIVE_ARGS[@]}"
