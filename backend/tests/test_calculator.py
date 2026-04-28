"""
Тесты агента-Расчётчика МК.
Запуск: python -m pytest backend/tests/test_calculator.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.agents.calculator import CalculatorAgent, _get_waste_factor
from app.schemas.calculator_schema import CalculatorRequest, MaterialInput

client = TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def agent():
    return CalculatorAgent()


def _mk_request(**overrides) -> CalculatorRequest:
    base = dict(
        mk_number="01-04.26",
        article="1.(П4.05.00.280)1.4.1",
        product_name="Уплотнение П4.05.00.280",
        quantity=4.0,
        materials=[
            MaterialInput(
                name="Лист г/к 10*1500*6000",
                unit="кг",
                qty_per_unit=1.716,
                qty_issued=15.4,
                unit_price=85.0,
                qty_in_stock=10.0,
            ),
            MaterialInput(
                name="Резиновая смесь 7-В-14",
                unit="кг",
                qty_per_unit=1.200,
                qty_issued=4.8,
                unit_price=320.0,
                qty_in_stock=20.0,
            ),
            MaterialInput(
                name="круг 16",
                unit="кг",
                qty_per_unit=0.090,
                qty_issued=0.4,
                unit_price=110.0,
                qty_in_stock=0.0,
            ),
        ],
    )
    base.update(overrides)
    return CalculatorRequest(**base)


# ---------------------------------------------------------------------------
# Тесты коэффициентов отхода
# ---------------------------------------------------------------------------

def test_waste_factor_manual():
    factor, source = _get_waste_factor("Лист г/к 10*1500*6000", 1.20)
    assert factor == 1.20
    assert source == "manual"


def test_waste_factor_rule_sheet():
    factor, source = _get_waste_factor("Лист г/к 10*1500*6000", None)
    assert factor == 1.15
    assert source == "rule"


def test_waste_factor_rule_rubber():
    factor, source = _get_waste_factor("Резиновая смесь 7-В-14", None)
    assert factor == 1.10
    assert source == "rule"


def test_waste_factor_rule_rod():
    factor, source = _get_waste_factor("круг 16", None)
    assert factor == 1.05
    assert source == "rule"


def test_waste_factor_default_unknown():
    factor, source = _get_waste_factor("Болт М12×40", None)
    assert factor == 1.00
    assert source == "default"


def test_waste_factor_bad_manual_clamped(agent):
    """Коэффициент < 1.0 → автоматически становится 1.0."""
    factor, source = _get_waste_factor("Лист", 0.5)
    assert factor == 1.0


# ---------------------------------------------------------------------------
# Тесты расчёта материалов
# ---------------------------------------------------------------------------

def test_qty_required_formula(agent):
    """qty_required = qty_per_unit × quantity × waste_factor"""
    req = _mk_request()
    result = agent.calculate(req)

    sheet = next(r for r in result.materials if "лист" in r.name.lower())
    # qty_per_unit=1.716, quantity=4, waste_factor=1.15
    expected = round(1.716 * 4.0 * 1.15, 4)
    assert sheet.qty_required == expected
    assert sheet.waste_factor == 1.15
    assert sheet.waste_factor_source == "rule"


def test_cost_formula(agent):
    """cost = qty_required × unit_price"""
    req = _mk_request()
    result = agent.calculate(req)

    sheet = next(r for r in result.materials if "лист" in r.name.lower())
    expected_cost = round(sheet.qty_required * 85.0, 4)
    assert sheet.cost == expected_cost


def test_qty_to_purchase_when_stock_insufficient(agent):
    """qty_to_purchase = qty_required - qty_in_stock если qty_in_stock < qty_required."""
    req = _mk_request()
    result = agent.calculate(req)

    rod = next(r for r in result.materials if "круг" in r.name.lower())
    # qty_in_stock=0.0 → всё нужно купить
    assert rod.qty_to_purchase == rod.qty_required
    assert rod.qty_to_purchase > 0


def test_qty_to_purchase_zero_when_stock_covers(agent):
    """Если склад покрывает — qty_to_purchase = 0."""
    req = _mk_request()
    result = agent.calculate(req)

    rubber = next(r for r in result.materials if "резин" in r.name.lower())
    # qty_in_stock=20.0, qty_required = 1.2*4*1.1 = 5.28 → покрывает
    assert rubber.qty_to_purchase == 0.0


def test_total_cost_calculated(agent):
    req = _mk_request()
    result = agent.calculate(req)
    assert result.has_prices is True
    assert result.total_cost is not None
    assert result.total_cost > 0
    print(f"\n  total_cost: {result.total_cost:.2f} руб.")


def test_needs_purchase_true(agent):
    req = _mk_request()
    result = agent.calculate(req)
    assert result.needs_purchase is True  # круг 16 нужно купить


def test_needs_purchase_false_when_stock_covers(agent):
    """Когда склад покрывает всё — needs_purchase=False."""
    req = _mk_request(
        materials=[
            MaterialInput(
                name="Лист г/к 10*1500*6000", unit="кг",
                qty_per_unit=1.716, unit_price=85.0,
                qty_in_stock=100.0,  # большой запас
            ),
        ]
    )
    result = agent.calculate(req)
    assert result.needs_purchase is False
    assert result.materials[0].qty_to_purchase == 0.0


def test_no_price_no_cost(agent):
    """Если unit_price не задан — cost=None, has_prices=False."""
    req = _mk_request(
        materials=[
            MaterialInput(name="Лист г/к", unit="кг", qty_per_unit=1.716),
        ]
    )
    result = agent.calculate(req)
    assert result.has_prices is False
    assert result.total_cost is None
    assert result.materials[0].cost is None


def test_snapshot_at_is_set(agent):
    req = _mk_request()
    result = agent.calculate(req)
    assert result.snapshot_at != ""
    assert "T" in result.snapshot_at  # ISO format


def test_summary_not_empty(agent):
    req = _mk_request()
    result = agent.calculate(req)
    assert len(result.agent_summary) > 20
    print(f"\n  summary: {result.agent_summary}")


def test_zero_quantity_raises(agent):
    with pytest.raises(ValueError, match="> 0"):
        agent.calculate(_mk_request(quantity=0))


def test_waste_factor_warning_on_big_discrepancy(agent):
    """Предупреждение если расчётное кол-во сильно отличается от qty_issued."""
    req = _mk_request(
        materials=[
            MaterialInput(
                name="Лист г/к 10*1500*6000", unit="кг",
                qty_per_unit=1.716, qty_issued=1.0,  # сильно меньше расчётного
            ),
        ]
    )
    result = agent.calculate(req)
    assert any("лист" in w.lower() for w in result.warnings)


def test_default_waste_override(agent):
    """default_waste_factor применяется если у материала нет явного и нет правила."""
    req = _mk_request(
        default_waste_factor=1.08,
        materials=[
            MaterialInput(name="Болт М12×40", unit="шт", qty_per_unit=8.0),
        ]
    )
    result = agent.calculate(req)
    assert result.materials[0].waste_factor == 1.08


# ---------------------------------------------------------------------------
# Тесты endpoint'а POST /api/mk/calculate
# ---------------------------------------------------------------------------

def test_calculate_endpoint_ok():
    payload = _mk_request().model_dump()
    resp = client.post("/api/mk/calculate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["mk_number"] == "01-04.26"
    assert data["total_cost"] is not None
    assert data["needs_purchase"] is True
    assert len(data["materials"]) == 3
    print(f"\n  total_cost: {data['total_cost']}, needs_purchase: {data['needs_purchase']}")


def test_calculate_endpoint_materials_fields():
    payload = _mk_request().model_dump()
    resp = client.post("/api/mk/calculate", json=payload)
    data = resp.json()
    for mat in data["materials"]:
        assert "qty_required" in mat
        assert "waste_factor" in mat
        assert "qty_to_purchase" in mat
        assert "waste_factor_source" in mat


def test_calculate_endpoint_zero_qty_422():
    payload = _mk_request(quantity=0).model_dump()
    resp = client.post("/api/mk/calculate", json=payload)
    assert resp.status_code == 422


def test_calculate_endpoint_snapshot_at():
    payload = _mk_request().model_dump()
    resp = client.post("/api/mk/calculate", json=payload)
    data = resp.json()
    assert data["snapshot_at"] != ""
