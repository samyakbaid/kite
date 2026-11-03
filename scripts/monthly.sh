#!/usr/bin/env bash
# Guided monthly rebalance:  scripts/monthly.sh [both|sells|buys]
#   preflight -> sell names that left the rank buffer -> wait for fills -> buy within free cash
# Pass "buys" to resume with only the buy step (e.g. next day, or after sells filled).
set -euo pipefail
WHICH="${1:-both}"
case "$WHICH" in both|sells|buys) ;; *) echo "usage: monthly.sh [both|sells|buys]" >&2; exit 2 ;; esac
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY=.venv/bin/python

read -r -p "Type LIVE to place real orders (anything else = dry run): " answer
MODE=dry_run
[[ "$answer" == "LIVE" ]] && MODE=live
echo "Mode: $MODE"

read -r -p "Log in to Kite now (needed once per day)? [Y/n] " login
if [[ "${login:-Y}" =~ ^[Yy]$ ]]; then $PY scripts/auth_kite.py; fi

echo; echo "=== PREFLIGHT ==="
if ! $PY scripts/preflight.py; then
  read -r -p "Preflight reported problems. Continue anyway? [y/N] " go
  [[ "$go" =~ ^[Yy]$ ]] || exit 1
fi

if [[ "$WHICH" != "buys" ]]; then
  echo; echo "=== STEP 1: SELL names that fell out of the rank buffer ==="
  EXECUTION_MODE=$MODE PHASE=sells EXITS_ONLY=YES MAX_TURNOVER=1.0 scripts/run_local_rebalance.sh
  if [[ "$MODE" == "live" ]]; then
    $PY scripts/order_status.py
    if [[ "$WHICH" == "both" ]]; then
      read -r -p "Press Enter once the sells show COMPLETE (Ctrl-C to stop here) " _
    fi
  fi
fi
[[ "$WHICH" == "sells" ]] && { echo "Sells step finished. Resume later with: scripts/monthly.sh buys"; exit 0; }

echo; echo "=== STEP 2: BUY within free cash (capped at ${BUY_TURNOVER:-0.20} turnover) ==="
[[ "$MODE" == "dry_run" ]] && echo "(dry run: holdings still include names step 1 would sell, so this preview is approximate)"
EXECUTION_MODE=$MODE PHASE=buys FIT_CASH=YES MAX_TURNOVER="${BUY_TURNOVER:-0.20}" scripts/run_local_rebalance.sh
if [[ "$MODE" == "live" ]]; then
  $PY scripts/order_status.py
  echo "Unfilled DAY orders expire at the close; place leftovers by hand or next month."
fi
echo; echo "Done."
