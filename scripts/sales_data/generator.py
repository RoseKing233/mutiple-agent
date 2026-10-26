"""Pure simulation. Database writes and forecasting are deliberately separate."""

from __future__ import annotations

import random
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from scripts.sales_data.config import GENERATOR_VERSION, PROFILES, SimulationConfig

NAMESPACE = uuid.UUID("ea5c5620-70b9-4c47-b726-010000000001")
ADDRESS = {
    "name": "Demo Customer",
    "street": "1 Demo St",
    "city": "Richmond",
    "state": "VA",
    "zip": "23220",
    "country": "US",
}


@dataclass
class Simulation:
    run_id: uuid.UUID
    config: SimulationConfig
    orders: list[dict[str, Any]] = field(default_factory=list)
    items: list[dict[str, Any]] = field(default_factory=list)
    statuses: list[dict[str, Any]] = field(default_factory=list)
    returns: list[dict[str, Any]] = field(default_factory=list)
    movements: list[dict[str, Any]] = field(default_factory=list)
    prices: list[dict[str, Any]] = field(default_factory=list)
    inventory: dict[tuple[uuid.UUID, uuid.UUID], int] = field(default_factory=dict)
    profiles: dict[str, str] = field(default_factory=dict)
    launches: dict[uuid.UUID, datetime] = field(default_factory=dict)
    demand_units: int = 0
    unfilled_units: int = 0


def generate(
    products: list[dict[str, Any]],
    warehouses: list[uuid.UUID],
    customers: list[uuid.UUID],
    config: SimulationConfig,
) -> Simulation:
    if not products or not warehouses or not customers:
        raise ValueError("Products, warehouses and customers must all be nonempty")
    if len(warehouses) != len(set(warehouses)) or len(products) != len({p["id"] for p in products}):
        raise ValueError("Duplicate product or warehouse identifiers")
    signature = ":".join(sorted(str(p["id"]) for p in products))
    run_id = uuid.uuid5(NAMESPACE, f"{GENERATOR_VERSION}:{config.seed}:{config.days}:{config.end_date}:{signature}")
    result = Simulation(run_id, config)

    for index, product in enumerate(products):
        pid = product["id"]
        profile = PROFILES[index % len(PROFILES)]
        # Preserve two familiar inventory demo cases while making their history coherent.
        if product["name"] in {"Dyson V15 Detect", "Sony WH-1000XM5"}:
            profile = "low_stock"
        result.profiles[str(pid)] = profile
        rng = random.Random(f"{config.seed}:{pid}")
        base = rng.uniform(1.0, 3.0) * (0.75 if Decimal(str(product["price"])) > 500 else 1)
        launch_day = config.days - 28 if profile == "new" else 0
        launched = datetime.combine(config.start_date + timedelta(days=launch_day), time(), UTC)
        result.launches[pid] = launched
        pending_returns: dict[int, list[dict[str, Any]]] = defaultdict(list)

        def movement(warehouse: uuid.UUID, delta: int, kind: str, moment: datetime, key: str, **refs: Any) -> None:
            pair = (pid, warehouse)
            balance = result.inventory.get(pair, 0) + delta
            if balance < 0:
                raise AssertionError("Simulation attempted negative inventory")
            result.inventory[pair] = balance
            result.movements.append(
                {
                    "event_key": f"{run_id}:{key}",
                    "product_id": pid,
                    "warehouse_id": warehouse,
                    "movement_type": kind,
                    "quantity_delta": delta,
                    "balance_after": balance,
                    "occurred_at": moment,
                    "order_id": None,
                    "order_item_id": None,
                    "return_id": None,
                    **refs,
                }
            )

        initial = max(5, round(base * (4 if profile == "low_stock" else 14)))
        for wi, warehouse in enumerate(warehouses):
            movement(warehouse, initial + wi, "opening", launched, f"opening:{pid}:{wi}")

        for day in range(launch_day, config.days):
            current = config.start_date + timedelta(days=day)
            morning = datetime.combine(current, time(7), UTC)
            # These are past receipts in a fixture, not purchase orders or future automation.
            total_stock = sum(result.inventory[(pid, wh)] for wh in warehouses)
            receipts_allowed = profile != "low_stock" or day < config.days - 21
            if total_stock < base * 9 and receipts_allowed:
                for wi, warehouse in enumerate(warehouses):
                    movement(
                        warehouse,
                        max(2, round(base * (3 if profile == "low_stock" else 12))),
                        "historical_receipt",
                        morning,
                        f"receipt:{pid}:{day}:{wi}",
                    )
            for received in pending_returns.pop(day, []):
                for wi, qty in received["allocations"]:
                    movement(
                        warehouses[wi],
                        qty,
                        "return_received",
                        morning + timedelta(hours=1),
                        f"return:{received['return_id']}:{wi}",
                        order_id=received["order_id"],
                        order_item_id=received["item_id"],
                        return_id=received["return_id"],
                    )

            progress = (day - launch_day) / max(1, config.days - launch_day - 1)
            trend = (
                0.55 + 1.0 * progress if profile == "growing" else 1.6 - 1.1 * progress if profile == "declining" else 1
            )
            weekly = (
                (1.7 if current.weekday() >= 5 else 0.72)
                if profile == "weekly"
                else (1.15 if current.weekday() >= 5 else 0.94)
            )
            promotion = day % 60 in range(38, 43)
            expected = base * trend * weekly * (1.5 if promotion else 1)
            demand = max(0, round(rng.gauss(expected, max(0.65, expected * 0.28))))
            if profile == "intermittent":
                demand = rng.randint(1, 3) if rng.random() < 0.17 else 0
            result.demand_units += demand
            price = (Decimal(str(product["price"])) * (Decimal("0.9") if promotion else Decimal("1"))).quantize(
                Decimal("0.01")
            )
            result.prices.append(
                {"product_id": pid, "price": price, "recorded_at": datetime.combine(current, time(), UTC)}
            )
            available = sum(result.inventory[(pid, wh)] for wh in warehouses)
            fulfilled = min(demand, available)
            result.unfilled_units += demand - fulfilled
            chunk = 0
            while fulfilled > 0:
                quantity = min(fulfilled, rng.randint(1, 3))
                fulfilled -= quantity
                created = morning + timedelta(hours=3, seconds=chunk * 15)
                oid = uuid.uuid5(run_id, f"order:{pid}:{day}:{chunk}")
                item_id = uuid.uuid5(oid, "item")
                age = config.days - 1 - day
                outcome = rng.random()
                cancelled = outcome < 0.04
                returned = 0.04 <= outcome < 0.065 and age >= 8
                flow = ["placed", "confirmed", "shipped", "out_for_delivery", "delivered"]
                final = "cancelled" if cancelled else "returned" if returned else flow[min(age, 4)]
                subtotal = price * quantity
                result.orders.append(
                    {
                        "id": oid,
                        "user_id": rng.choice(customers),
                        "status": final,
                        "total": subtotal,
                        "created_at": created,
                    }
                )
                result.items.append(
                    {
                        "id": item_id,
                        "order_id": oid,
                        "product_id": pid,
                        "quantity": quantity,
                        "unit_price": price,
                        "subtotal": subtotal,
                    }
                )
                steps = ["placed", "cancelled"] if cancelled else flow[: min(age, 4) + 1]
                for step, status in enumerate(steps):
                    moment = created + (timedelta(seconds=1) if cancelled and step else timedelta(days=step))
                    result.statuses.append({"order_id": oid, "status": status, "timestamp": moment})
                remaining = quantity
                allocations = []
                ranked = sorted(enumerate(warehouses), key=lambda wh: (-result.inventory[(pid, wh[1])], wh[0]))
                for wi, warehouse in ranked:
                    take = min(remaining, result.inventory[(pid, warehouse)])
                    if take:
                        movement(
                            warehouse, -take, "sale", created, f"sale:{oid}:{wi}", order_id=oid, order_item_id=item_id
                        )
                        allocations.append((wi, take))
                        remaining -= take
                    if remaining == 0:
                        break
                if cancelled:
                    for wi, qty in allocations:
                        movement(
                            warehouses[wi],
                            qty,
                            "cancel_release",
                            created + timedelta(seconds=1),
                            f"cancel:{oid}:{wi}",
                            order_id=oid,
                            order_item_id=item_id,
                        )
                if returned:
                    rid = uuid.uuid5(oid, "return")
                    requested = created + timedelta(days=5)
                    received = (created + timedelta(days=7)).replace(hour=8, minute=0, second=0)
                    result.returns.append(
                        {
                            "id": rid,
                            "order_id": oid,
                            "user_id": result.orders[-1]["user_id"],
                            "refund_amount": subtotal,
                            "created_at": requested,
                            "resolved_at": received,
                        }
                    )
                    result.statuses.append({"order_id": oid, "status": "returned", "timestamp": requested})
                    pending_returns[day + 7].append(
                        {"return_id": rid, "order_id": oid, "item_id": item_id, "allocations": allocations}
                    )
                chunk += 1

    result.movements.sort(key=lambda row: row["occurred_at"])
    return result
