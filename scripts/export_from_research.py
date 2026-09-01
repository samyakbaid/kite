#!/usr/bin/env python3
"""Export compact live signals/model metadata from the research repository."""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_prices(path):
    path = Path(path)
    if path.suffix.lower() in {".pkl", ".pickle"}:
        frame = pd.read_pickle(path)
    else:
        frame = pd.read_parquet(path)
    frame.index = pd.to_datetime(frame.index)
    return frame


def ridge_fit_predict(train, pred, features, alpha):
    X = train[features].to_numpy(dtype=float)
    y = train["target"].to_numpy(dtype=float)
    mean = X.mean(axis=0)
    scale = X.std(axis=0)
    scale[scale < 1e-9] = 1.0
    standardized = (X - mean) / scale
    intercept = y.mean()
    coefficients = np.linalg.solve(
        standardized.T @ standardized + alpha * np.eye(standardized.shape[1]),
        standardized.T @ (y - intercept),
    )
    pred_x = (pred[features].to_numpy(dtype=float) - mean) / scale
    scores = intercept + pred_x @ coefficients
    artifact = {
        "type": "standardized_ridge",
        "alpha": alpha,
        "features": list(features),
        "feature_mean": mean.tolist(),
        "feature_scale": scale.tolist(),
        "intercept": float(intercept),
        "coefficients": coefficients.tolist(),
        "training_rows": len(train),
        "training_months": int(train["month_idx"].nunique()),
        "trained_targets_through": str(pd.Timestamp(train["target_date"].max()).date()),
    }
    return pd.Series(scores, index=pred["stock"].values), artifact


def write_signal_file(path, signal_date, model, universe_kind, scores, n_hold):
    ranked = scores.replace([np.inf, -np.inf], np.nan).dropna().sort_values(ascending=False)
    frame = pd.DataFrame(
        {
            "signal_date": str(pd.Timestamp(signal_date).date()),
            "model": model,
            "universe_kind": universe_kind,
            "rank": np.arange(1, len(ranked) + 1),
            "symbol": ranked.index,
            "score": ranked.values,
            "target_weight": [1.0 / n_hold if rank <= n_hold else 0.0 for rank in range(1, len(ranked) + 1)],
        }
    )
    frame.to_csv(path, index=False)
    return len(frame)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--research-dir", required=True)
    parser.add_argument("--prices", required=True)
    parser.add_argument("--members", required=True)
    parser.add_argument("--output-dir", default="artifacts")
    parser.add_argument(
        "--membership-kind", choices=["proxy", "provided", "official"], default="proxy"
    )
    parser.add_argument("--top-n", type=int, default=250)
    parser.add_argument("--n-hold", type=int, default=30)
    parser.add_argument("--min-train-months", type=int, default=48)
    parser.add_argument("--ridge-lambda", type=float, default=25.0)
    return parser.parse_args()


def main():
    args = parse_args()
    research_dir = Path(args.research_dir).resolve()
    sys.path.insert(0, str(research_dir))
    from ml_backtest_pit import momentum_predictor, prepare_backtest_data
    from ml_dataset import train_predict_slices

    prices_path = Path(args.prices).resolve()
    members_path = Path(args.members).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    prices = load_prices(prices_path)
    panel, features = prepare_backtest_data(
        prices,
        membership_path=str(members_path),
        top_n=args.top_n,
        membership_kind=args.membership_kind,
        drop_partial_last_month=True,
    )
    signal_month = int(panel["month_idx"].max())
    train, pred = train_predict_slices(panel, signal_month, features)
    train = train.loc[train["eligible"]]
    pred = pred.loc[pred["eligible"]]
    if train["month_idx"].nunique() < args.min_train_months:
        raise RuntimeError("not enough point-in-time training months")
    if len(pred) < args.n_hold:
        raise RuntimeError("not enough eligible names for the requested portfolio")
    signal_date = pd.Timestamp(pred["date"].iloc[0])

    momentum_scores = momentum_predictor(train, pred, features)
    ridge_scores, ridge_artifact = ridge_fit_predict(
        train, pred, features, args.ridge_lambda
    )
    ridge_artifact.update(
        {
            "signal_date": str(signal_date.date()),
            "membership_kind": args.membership_kind,
            "n_hold": args.n_hold,
        }
    )

    momentum_path = output_dir / "signals_momentum.csv"
    ridge_path = output_dir / "signals_ridge.csv"
    model_path = output_dir / "ridge_model.json"
    counts = {
        "momentum": write_signal_file(
            momentum_path,
            signal_date,
            "momentum_12_1",
            args.membership_kind,
            momentum_scores,
            args.n_hold,
        ),
        "ridge": write_signal_file(
            ridge_path,
            signal_date,
            f"ridge_lambda_{args.ridge_lambda:g}",
            args.membership_kind,
            ridge_scores,
            args.n_hold,
        ),
    }
    model_path.write_text(json.dumps(ridge_artifact, indent=2) + "\n", encoding="utf-8")

    manifest = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "signal_date": str(signal_date.date()),
        "last_price_date": str(pd.Timestamp(prices.index.max()).date()),
        "partial_last_month_dropped": bool(
            panel.attrs.get("dropped_partial_last_month")
        ),
        "membership_kind": args.membership_kind,
        "universe_source": panel.attrs.get("universe_source"),
        "n_hold": args.n_hold,
        "eligible_names": counts,
        "files": {
            momentum_path.name: sha256_file(momentum_path),
            ridge_path.name: sha256_file(ridge_path),
            model_path.name: sha256_file(model_path),
        },
        "warning": (
            "Research-only liquidity-proxy universe; replace with official historical "
            "membership before relying on the strategy."
            if args.membership_kind != "official"
            else None
        ),
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Exported {signal_date.date()} Ridge and momentum artifacts to {output_dir}")


if __name__ == "__main__":
    main()
