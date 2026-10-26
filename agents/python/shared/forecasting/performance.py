"""Evidence-backed product flags, with explicit insufficient-data outcomes."""

from typing import Any

from shared.forecasting.config import PerformanceRules
from shared.forecasting.data import ProductHistory


def assess(history: ProductHistory, rules: PerformanceRules) -> dict[str, Any]:
    values = history.sales_at(history.days[-1]) if history.days else []
    width = rules.comparison_days
    recent, previous = sum(values[-width:]), sum(values[-2 * width : -width])
    stock = history.stock[-1] if history.stock else None
    daily = recent / width if len(values) >= width else None
    coverage = stock / daily if stock is not None and daily else None
    zero_days = 0
    for value in reversed(values):
        if value > 0:
            break
        zero_days += 1
    recent_known = len(values) >= max(width, rules.no_sale_days) and history.status_complete
    recent_stock_known = recent_known and all(
        s is not None and s > 0 for s in history.stock[-max(width, rules.no_sale_days) :]
    )
    unconstrained = recent_stock_known and not any(history.constrained[-max(width, rules.no_sale_days) :])
    trend = "insufficient_history"
    rate = (recent - previous) / previous * 100 if previous else None
    if len(values) >= 2 * width and history.status_complete:
        if any(s is None for s in history.stock[-2 * width :]):
            trend = "unknown_stock_history"
        elif any(history.constrained[-2 * width :]):
            trend = "stockout_affected"
        elif previous == 0:
            trend = "new_sales" if recent else "stable"
        elif rate >= rules.trend_percent and recent - previous >= rules.trend_min_units:
            trend = "growing"
        elif rate <= -rules.trend_percent and previous - recent >= rules.trend_min_units:
            trend = "declining"
        else:
            trend = "stable"
    slow = bool(recent <= rules.slow_max_units or zero_days >= rules.no_sale_days) if unconstrained else None
    overstock = (
        bool(stock >= rules.overstock_min_units and coverage is not None and coverage > rules.overstock_days)
        if unconstrained
        else None
    )
    reasons = list(history.warnings)
    if not recent_known:
        reasons.append("Insufficient complete sales history for slow-moving/overstock assessment")
    elif not unconstrained:
        reasons.append("Recent stock was zero or unknown; slow-moving/overstock flags are withheld")
    if daily == 0:
        reasons.append("No recent sales: days of cover is undefined, not infinite")
    return {
        "trend": trend,
        "slow_moving": slow,
        "overstock": overstock,
        "recent_units": recent,
        "previous_units": previous if len(values) >= 2 * width else None,
        "growth_percent": round(rate, 2) if rate is not None and len(values) >= 2 * width else None,
        "consecutive_zero_days": zero_days,
        "consecutive_zero_sales_days": zero_days,
        "recent_stockout_days": sum(history.constrained[-width:]),
        "trend_stockout_days": sum(history.constrained[-2 * width :]),
        "stock_at_cutoff": stock,
        "days_of_cover": round(coverage, 2) if coverage is not None else None,
        "no_recent_sales": recent_known and recent == 0,
        "comparison_days": width,
        "recent_start": str(history.days[-width]) if len(values) >= width else None,
        "previous_start": str(history.days[-2 * width]) if len(values) >= 2 * width else None,
        "warnings": reasons,
    }
