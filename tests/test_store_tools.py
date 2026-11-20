"""Herramientas de negocio: catálogo, SKUs y validación de email en pedidos."""

from __future__ import annotations

import pytest

from src.tools.store_tools import (
    catalog_skus,
    check_order_status,
    get_product_by_sku,
    search_catalog,
)


def test_catalog_has_12_products_with_required_fields():
    from src.tools.store_tools import _catalog

    products = _catalog()
    assert len(products) == 12
    required = {"sku", "name", "category", "price_ars", "stock", "specs", "shipping_days"}
    for product in products:
        assert required <= product.keys()
    assert len(catalog_skus()) == 12


def test_search_is_deterministic_and_accent_insensitive():
    first = [p["sku"] for p in search_catalog("Parlantes portátiles")]
    second = [p["sku"] for p in search_catalog("Parlantes portatiles")]
    assert first == second == ["AUD-002"]


def test_search_respects_max_price():
    skus = [p["sku"] for p in search_catalog("auriculares", max_price=100000)]
    assert "AUD-001" not in skus  # cuesta 129.900 ARS
    assert "AUD-003" in skus


def test_search_without_useful_terms_returns_nothing():
    assert search_catalog("hola que tal") == []
    assert search_catalog("") == []


def test_search_rejects_invalid_max_price():
    with pytest.raises(ValueError):
        search_catalog("cargador", max_price=-1)
    with pytest.raises(ValueError):
        search_catalog("cargador", max_price=True)


def test_search_results_expose_stock_flag():
    by_sku = {p["sku"]: p for p in search_catalog("cable lightning")}
    assert by_sku["CAB-002"]["in_stock"] is False


def test_get_product_by_sku_normalizes_and_handles_unknown():
    product = get_product_by_sku("  aud-001 ")
    assert product is not None and product["sku"] == "AUD-001"
    assert get_product_by_sku("ZZZ-999") is None
    assert get_product_by_sku("no-es-sku") is None


def test_order_status_requires_exact_email_match():
    ok = check_order_status("ORD-1001", "ana.perez@example.com")
    assert ok["found"] is True and ok["status"] == "shipped"
    assert ok["tracking_code"] == "TRK-AR-884213"


def test_order_status_wrong_email_is_indistinguishable_from_missing_order():
    wrong_email = check_order_status("ORD-1001", "otra.persona@example.com")
    missing_order = check_order_status("ORD-9999", "ana.perez@example.com")
    assert wrong_email == missing_order == {"found": False, "reason": "not_found"}


def test_order_status_never_returns_customer_email():
    result = check_order_status("ORD-1001", "ana.perez@example.com")
    assert "customer_email" not in result
    assert "ana.perez@example.com" not in str(result)


@pytest.mark.parametrize("bad_email", ["", "sin-arroba", "ana@", "ana perez@example.com"])
def test_order_status_rejects_invalid_email_format(bad_email):
    result = check_order_status("ORD-1001", bad_email)
    assert result == {"found": False, "reason": "invalid_email"}


def test_order_status_rejects_malformed_order_id():
    assert check_order_status("1001", "ana.perez@example.com")["found"] is False
