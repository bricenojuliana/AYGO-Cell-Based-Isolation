"""Order rules shared by every cell. No AWS types here (SPEC RF01, RF02)."""
from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from typing import Any

CURRENCY = "COP"
MAX_LINES = 10
MIN_QUANTITY, MAX_QUANTITY = 1, 10
MAX_UNIT_PRICE_CENTS = 100_000_000
SKU_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
TENANT_PATTERN = re.compile(r"^[a-z0-9-]{3,40}$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Crockford base32 order codes, reused from Campus Café (ids.py).
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
ORDER_ID_PATTERN = re.compile(r"^CC-[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}$")


class DomainError(Exception):
    """Business error; `code`, `status` and `message` are part of the public API."""

    code = "DOMAIN_ERROR"
    status = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidRequest(DomainError):
    code = "INVALID_REQUEST"


class OrderNotFound(DomainError):
    code = "ORDER_NOT_FOUND"
    status = 404

    def __init__(self) -> None:
        super().__init__("This order does not exist.")


@dataclass(frozen=True)
class OrderItem:
    sku: str
    quantity: int
    unit_price_cents: int

    @property
    def subtotal_cents(self) -> int:
        return self.quantity * self.unit_price_cents

    def to_api(self) -> dict:
        return {"sku": self.sku, "quantity": self.quantity, "unitPriceCents": self.unit_price_cents}


@dataclass(frozen=True)
class Order:
    tenant_id: str
    order_id: str
    items: tuple[OrderItem, ...]
    created_at: str  # ISO-8601 UTC, e.g. 2026-11-19T14:03:00Z

    @property
    def total_cents(self) -> int:
        return sum(item.subtotal_cents for item in self.items)

    @property
    def day(self) -> str:
        return self.created_at[:10]

    def to_api(self) -> dict:
        return {
            "orderId": self.order_id,
            "items": [item.to_api() for item in self.items],
            "totalCents": self.total_cents,
            "currency": CURRENCY,
            "createdAt": self.created_at,
        }


@dataclass(frozen=True)
class DailyReport:
    day: str
    orders: int
    total_cents: int

    def to_api(self) -> dict:
        return {"day": self.day, "orders": self.orders, "totalCents": self.total_cents, "currency": CURRENCY}


def new_order_id() -> str:
    chars = "".join(secrets.choice(_ALPHABET) for _ in range(8))
    return f"CC-{chars[:4]}-{chars[4:]}"


def validate_tenant_id(tenant_id: Any) -> str:
    if not isinstance(tenant_id, str) or not TENANT_PATTERN.match(tenant_id):
        raise InvalidRequest("Invalid tenant id.")
    return tenant_id


def validate_order_id(order_id: Any) -> str:
    if not isinstance(order_id, str) or not ORDER_ID_PATTERN.match(order_id):
        raise OrderNotFound()
    return order_id


def validate_day(day: Any) -> str:
    if not isinstance(day, str) or not DATE_PATTERN.match(day):
        raise InvalidRequest("The day must have the form YYYY-MM-DD.")
    return day


def _positive_int(value: Any, low: int, high: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise InvalidRequest(f"'{field}' must be an integer between {low} and {high}.")
    return value


def parse_items(body: Any) -> tuple[OrderItem, ...]:
    """Validates {"items": [{"sku", "quantity", "unitPriceCents"}]} (1-10 distinct SKUs)."""
    if not isinstance(body, dict) or set(body) != {"items"}:
        raise InvalidRequest("The body must be a JSON object with only an 'items' list.")
    raw = body["items"]
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_LINES:
        raise InvalidRequest(f"'items' must contain between 1 and {MAX_LINES} lines.")
    items, seen = [], set()
    for line in raw:
        if not isinstance(line, dict) or set(line) != {"sku", "quantity", "unitPriceCents"}:
            raise InvalidRequest("Each line needs exactly 'sku', 'quantity' and 'unitPriceCents'.")
        sku = line["sku"]
        if not isinstance(sku, str) or not SKU_PATTERN.match(sku) or sku in seen:
            raise InvalidRequest("Each 'sku' must be a distinct code of 1-40 letters, digits, '_' or '-'.")
        seen.add(sku)
        items.append(OrderItem(
            sku=sku,
            quantity=_positive_int(line["quantity"], MIN_QUANTITY, MAX_QUANTITY, "quantity"),
            unit_price_cents=_positive_int(line["unitPriceCents"], 1, MAX_UNIT_PRICE_CENTS, "unitPriceCents"),
        ))
    return tuple(sorted(items, key=lambda item: item.sku))


def build_report(day: str, orders: list[Order]) -> DailyReport:
    return DailyReport(day=day, orders=len(orders), total_cents=sum(order.total_cents for order in orders))
