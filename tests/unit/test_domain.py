import pytest

from cellsaas.domain import (
    ORDER_ID_PATTERN,
    InvalidRequest,
    Order,
    OrderItem,
    OrderNotFound,
    build_report,
    new_order_id,
    parse_items,
    validate_day,
    validate_order_id,
    validate_tenant_id,
)


def _body(*lines):
    return {"items": list(lines)}


def _line(sku="CAFE", quantity=2, price=250_000):
    return {"sku": sku, "quantity": quantity, "unitPriceCents": price}


def test_rf01_parses_valid_items_sorted_by_sku():
    items = parse_items(_body(_line("TINTO"), _line("AREPA", 1, 500_000)))
    assert [i.sku for i in items] == ["AREPA", "TINTO"]


@pytest.mark.parametrize("body", [
    None, [], {}, {"items": []}, {"items": "x"}, {"items": [_line()], "totalCents": 1},
    _body(*[_line(f"S{i}") for i in range(11)]),
    _body(_line(quantity=0)), _body(_line(quantity=11)), _body(_line(quantity=True)), _body(_line(quantity="2")),
    _body(_line(price=0)), _body(_line(sku="bad sku")), _body(_line("A"), _line("A")),
    _body({"sku": "A", "quantity": 1}),
])
def test_rf01_rejects_invalid_bodies(body):
    with pytest.raises(InvalidRequest):
        parse_items(body)


def test_order_total_and_day():
    order = Order("cafe-01", "CC-AAAA-BBBB", (OrderItem("A", 2, 100), OrderItem("B", 1, 50)), "2026-11-19T10:00:00Z")
    assert order.total_cents == 250
    assert order.day == "2026-11-19"
    assert order.to_api()["totalCents"] == 250


def test_order_ids_are_well_formed_and_validated():
    order_id = new_order_id()
    assert ORDER_ID_PATTERN.match(order_id)
    assert validate_order_id(order_id) == order_id
    with pytest.raises(OrderNotFound):
        validate_order_id("../etc")


def test_tenant_and_day_validation():
    assert validate_tenant_id("cafe-01") == "cafe-01"
    with pytest.raises(InvalidRequest):
        validate_tenant_id("Cafe 01")
    assert validate_day("2026-11-19") == "2026-11-19"
    with pytest.raises(InvalidRequest):
        validate_day("19/11/2026")


def test_rf02_report_sums_orders():
    orders = [Order("t-1", f"CC-AAAA-000{i}", (OrderItem("A", 1, 100),), "2026-11-19T00:00:00Z") for i in range(3)]
    report = build_report("2026-11-19", orders)
    assert (report.orders, report.total_cents) == (3, 300)
