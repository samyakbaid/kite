#!/usr/bin/env bash
set -euo pipefail

REPO_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_DIR"

if [[ ! -d .venv ]]; then
  echo "Missing .venv. Run: python3 -m venv .venv && .venv/bin/pip install -e ." >&2
  exit 2
fi
# Remember what the caller typed so .env cannot silently override it.
CALLER_MODE="${EXECUTION_MODE-}"
CALLER_ARGS=("$@")
if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi
: "${STRATEGY_CAPITAL:?Set STRATEGY_CAPITAL in .env or the environment}"

STRATEGY_MODEL=${STRATEGY_MODEL:-momentum}
EXECUTION_MODE=${CALLER_MODE:-${EXECUTION_MODE:-dry_run}}
case "$STRATEGY_MODEL" in
  momentum) SIGNAL_FILE="artifacts/signals_momentum.csv" ;;
  ridge) SIGNAL_FILE="artifacts/signals_ridge.csv" ;;
  *) echo "STRATEGY_MODEL must be momentum or ridge" >&2; exit 2 ;;
esac

# Pull only code/artifacts. Local credentials, receipts, and state are ignored by Git.
git pull --ff-only

set --

if [[ "$EXECUTION_MODE" == "live" ]]; then
  set -- "$@" --live --confirm-live PLACE_ORDERS
elif [[ "$EXECUTION_MODE" != "dry_run" ]]; then
  echo "EXECUTION_MODE must be dry_run or live" >&2
  exit 2
fi
if [[ "${ALLOW_PROXY_UNIVERSE:-NO}" == "YES_I_ACCEPT_PROXY_RISK" ]]; then
set -- "$@" --allow-proxy-universe
fi
if [[ "${BOOTSTRAP:-NO}" == "YES" ]]; then
  set -- "$@" --bootstrap
fi
if [[ -n "${MAX_WEIGHT:-}" ]]; then
  set -- "$@" --max-weight "$MAX_WEIGHT"
fi
if [[ -n "${MAX_TURNOVER:-}" ]]; then
  set -- "$@" --max-turnover "$MAX_TURNOVER"
fi
if [[ "${FORCE:-NO}" == "YES" ]]; then
  set -- "$@" --force
fi

mkdir -p .trading_state receipts
LOCK_DIR=".trading_state/${STRATEGY_MODEL}.lockdir"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "Another rebalance may be running for ${STRATEGY_MODEL}." >&2
  echo "If no process is running, remove it with: rmdir '$LOCK_DIR'" >&2
  exit 3
fi

cleanup_lock() {
  rmdir "$LOCK_DIR" 2>/dev/null || true
}
trap cleanup_lock EXIT INT TERM HUP

.venv/bin/trading-rebalance \
  --signals "$SIGNAL_FILE" \
  --capital "$STRATEGY_CAPITAL" \
  --state-file ".trading_state/${STRATEGY_MODEL}.json" \
  --receipt-dir receipts \
  "$@" \
  ${CALLER_ARGS[@]+"${CALLER_ARGS[@]}"}
