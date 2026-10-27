"""Small deterministic forecast candidates and rolling-origin selection.

Holt-Winters uses additive seasonality (period=7), damped/additive trend,
and a documented finite parameter grid rather than numerical optimisation.
TSB smooths demand occurrence each day and positive demand size separately.
Equations: https://otexts.com/fpp3/exponential-smoothing.html
"""

from __future__ import annotations

from statistics import mean
from typing import Any

from shared.forecasting.data import ProductHistory

CANDIDATES = ["mean_28", "seasonal_naive_7", "tsb_0.1", "tsb_0.3"] + [
    f"holt_winters_{alpha}_{phi}" for alpha in (0.2, 0.5) for phi in (0.9, 1.0)
]


def predict(values: list[float], horizon: int, model: str) -> list[float]:
    if not values:
        raise ValueError("Cannot forecast an empty series")
    if model == "mean_28":
        return [mean(values[-28:])] * horizon
    if model == "seasonal_naive_7":
        return [values[-7:][i % min(7, len(values))] for i in range(horizon)]
    if model.startswith("tsb_"):
        beta = float(model.split("_")[1])
        positive = next((i for i, y in enumerate(values) if y > 0), None)
        if positive is None:
            return [0.0] * horizon
        size, probability = values[positive], 1 / (positive + 1)
        for y in values[positive + 1 :]:
            probability += beta * (float(y > 0) - probability)
            if y > 0:
                size += 0.2 * (y - size)
        return [size * probability] * horizon
    if not model.startswith("holt_winters_") or len(values) < 14:
        raise ValueError("Unknown model or insufficient seasonal history")
    alpha, phi = map(float, model.split("_")[-2:])
    beta, gamma = 0.1, 0.2
    level = mean(values[:7])
    trend = (mean(values[7:14]) - level) / 7
    seasonal = [y - level for y in values[:7]]
    for t in range(7, len(values)):
        y, old_level, old_trend, old_season = values[t], level, trend, seasonal[t % 7]
        level = alpha * (y - old_season) + (1 - alpha) * (level + phi * trend)
        trend = beta * (level - old_level) + (1 - beta) * phi * trend
        seasonal[t % 7] = gamma * (y - old_level - phi * old_trend) + (1 - gamma) * old_season
    return [
        max(0.0, level + sum(phi**j for j in range(1, h + 1)) * trend + seasonal[(len(values) + h - 1) % 7])
        for h in range(1, horizon + 1)
    ]


def prepare(values: list[float], constrained: list[bool]) -> tuple[list[float], int]:
    """Impute <=3-day stockout runs from earlier same weekdays only (no lookahead)."""
    output, filled = list(values), 0
    i = 0
    while i < len(values):
        if not constrained[i]:
            i += 1
            continue
        end = i
        while end < len(values) and constrained[end]:
            end += 1
        if end - i <= 3:
            for t in range(i, end):
                earlier = [values[k] for k in range(t - 7, max(-1, t - 29), -7) if not constrained[k]]
                if earlier:
                    output[t] = max(values[t], mean(earlier))
                    filled += 1
        i = end
    return output, filled


def quantile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * p
    low = int(index)
    return ordered[low] + (ordered[min(low + 1, len(ordered) - 1)] - ordered[low]) * (index - low)


def fit_forecast(history: ProductHistory, horizon: int) -> dict[str, Any]:
    n = len(history.days)
    warnings = list(history.warnings)
    if n < 7 or not history.status_complete:
        return {
            "available": False,
            "reason": "At least 7 known days and complete order-status history are required",
            "warnings": warnings,
            "training_days": n,
        }
    if sum(history.constrained[-28:]) > len(history.constrained[-28:]) * 0.2:
        return {
            "available": False,
            "reason": "Stockouts affect over 20% of recent days; observed sales understate demand",
            "warnings": warnings,
            "training_days": n,
        }
    actual = history.sales_at(history.days[-1])
    values, imputed = prepare(actual, history.constrained)
    if imputed:
        warnings.append(f"{imputed} short stockout days estimated from earlier same weekdays")
    remaining_stockouts = sum(history.constrained) - imputed
    if remaining_stockouts:
        warnings.append(
            f"{remaining_stockouts} stockout-affected days retain observed sales; forecasts may understate demand"
        )
    folds = []
    # Disjoint validation windows, each with >=28 training days. All preparation
    # and status reconstruction are repeated at that fold's own cutoff.
    for split in [n - horizon * i for i in (3, 2, 1)]:
        if split < 28 or any(history.constrained[split : split + horizon]):
            continue
        train = history.sales_at(history.days[split - 1])
        if sum(history.constrained[max(0, split - 28) : split]) > min(split, 28) * 0.2:
            continue
        train, _ = prepare(train, history.constrained[:split])
        target = history.sales_at(history.days[split + horizon - 1])[split:]
        folds.append((split, train, target))
    scores, residuals = [], {}
    for model in CANDIDATES:
        errors, totals = [], []
        for _, train, target in folds:
            prediction = predict(train, horizon, model)
            errors.extend(y - f for y, f in zip(target, prediction, strict=True))
            totals.append(abs(sum(target) - sum(prediction)))
        if errors:
            residuals[model] = errors
            scores.append(
                {
                    "model": model,
                    "mae": mean(abs(e) for e in errors),
                    "horizon_total_mae": mean(totals),
                    "folds": len(folds),
                }
            )
    scores.sort(key=lambda s: (s["mae"], s["horizon_total_mae"], CANDIDATES.index(s["model"])))
    selected = scores[0]["model"] if len(folds) >= 2 else "mean_28"
    if len(folds) < 2:
        warnings.append("Too few rolling-origin folds; recent-mean fallback, low reliability")
    if not any(actual):
        warnings.append("No observed sales; a zero forecast is not proof of no future demand")
    prediction = predict(values, horizon, selected)
    errors = residuals.get(selected, [])
    # Descriptive spread only. Selection and residual estimation share folds;
    # this is deliberately NOT labelled a calibrated 80% prediction interval.
    spread = len(folds) >= 3 and len(errors) >= 21
    low, high = (min(0, quantile(errors, 0.1)), max(0, quantile(errors, 0.9))) if spread else (0, 0)
    return {
        "available": True,
        "model": selected,
        "training_days": n,
        "training_start": str(history.days[0]),
        "imputed_days": imputed,
        "reliability": "low" if warnings or n < 56 else "moderate",
        "warnings": warnings,
        "units": prediction,
        "lower": [max(0, y + low) for y in prediction] if spread else None,
        "upper": [y + high for y in prediction] if spread else None,
        "uncertainty": "Empirical daily residual p10/p90 scenario; not a calibrated confidence interval"
        if spread
        else "Insufficient backtests for an empirical range",
        "backtest": {
            "scores": scores,
            "folds": [
                {"cutoff": str(history.days[i - 1]), "validation_end": str(history.days[i + horizon - 1])}
                for i, _, _ in folds
            ],
            "note": "Model-selection errors, not independent test-set accuracy",
        },
    }
