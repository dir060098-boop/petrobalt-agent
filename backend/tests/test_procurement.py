"""
Тесты агента-Закупщика (без реальных API — только детерминированная логика).
Запуск: python -m pytest backend/tests/test_procurement.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.agents.procurement import ProcurementAgent, _build_rfq_letter, _build_search_query
from app.schemas.procurement_schema import (
    ProcurementMaterial,
    ProcurementRequest,
    RFQItem,
)

client = TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _materials() -> list:
    return [
        ProcurementMaterial(
            name="Лист г/к 10*1500*6000",
            unit="кг",
            qty_to_purchase=7.85,
            unit_price_target=85.0,
        ),
        ProcurementMaterial(
            name="Резиновая смесь 7-В-14",
            unit="кг",
            qty_to_purchase=0.0,   # не нужно закупать
        ),
        ProcurementMaterial(
            name="круг 16",
            unit="кг",
            qty_to_purchase=0.378,
        ),
    ]


def _request(**overrides) -> ProcurementRequest:
    base = dict(
        mk_number="01-04.26",
        article="1.(П4.05.00.280)1.4.1",
        product_name="Уплотнение П4.05.00.280",
        materials=_materials(),
        region="Калининград",
        company_name='ООО "Петробалт Сервис"',
        contact_person="Иванов И.И.",
    )
    base.update(overrides)
    return ProcurementRequest(**base)


@pytest.fixture(scope="module")
def agent_no_api():
    """Агент без API ключей — только детерминированная логика."""
    return ProcurementAgent(anthropic_api_key="", tavily_api_key="")


# ---------------------------------------------------------------------------
# Тесты вспомогательных функций
# ---------------------------------------------------------------------------

def test_search_query_contains_material_name():
    mat = ProcurementMaterial(name="Лист г/к 10*1500*6000", unit="кг", qty_to_purchase=5.0)
    query = _build_search_query(mat, "Калининград")
    assert "Лист г/к" in query
    assert "Калининград" in query


def test_search_query_includes_gost():
    mat = ProcurementMaterial(
        name="Лист г/к 10*1500*6000", unit="кг",
        qty_to_purchase=5.0, gost="ГОСТ 19903-2015",
    )
    query = _build_search_query(mat, "Калининград")
    assert "ГОСТ 19903-2015" in query


def test_rfq_letter_contains_material():
    items = [RFQItem(material_name="Лист г/к 10*1500*6000", unit="кг", quantity=7.85)]
    letter = _build_rfq_letter(
        supplier_name="ООО Металлоторг",
        supplier_contact="info@metal.ru",
        items=items,
        company_name='ООО "Петробалт Сервис"',
        contact_person="Иванов И.И.",
        region="Калининград",
    )
    assert "Лист г/к 10*1500*6000" in letter.body
    assert "7.85" in letter.body
    assert "ООО Металлоторг" in letter.supplier_name
    assert letter.subject != ""


def test_rfq_letter_contains_company():
    items = [RFQItem(material_name="круг 16", unit="кг", quantity=0.378)]
    letter = _build_rfq_letter(
        supplier_name="Поставщик",
        supplier_contact=None,
        items=items,
        company_name='ООО "Петробалт Сервис"',
        contact_person="",
        region="Калининград",
    )
    assert "Петробалт" in letter.body


def test_rfq_letter_target_price_shown():
    items = [RFQItem(material_name="Лист г/к", unit="кг", quantity=5.0, target_price=85.0)]
    letter = _build_rfq_letter("X", None, items, "ООО Y", "", "Москва")
    assert "85.00" in letter.body


# ---------------------------------------------------------------------------
# Тесты агента без API
# ---------------------------------------------------------------------------

def test_empty_materials_returns_early(agent_no_api):
    req = _request(materials=[])
    result = agent_no_api.procure(req)
    assert result.materials_to_purchase == []
    assert "пуст" in result.agent_summary.lower()


def test_fallback_rfq_generated(agent_no_api):
    """Без API ключей — должно сформироваться шаблонное письмо."""
    req = _request()
    result = agent_no_api.procure(req)
    assert len(result.rfq_letters) >= 1
    rfq = result.rfq_letters[0]
    assert rfq.body != ""
    assert rfq.subject != ""


def test_fallback_rfq_contains_all_materials(agent_no_api):
    """Шаблонное письмо включает все материалы к закупке."""
    req = _request()
    result = agent_no_api.procure(req)
    rfq = result.rfq_letters[0]
    # все материалы с qty_to_purchase > 0
    assert len(rfq.items) == len(req.materials)  # fallback включает все
    names = [item.material_name for item in rfq.items]
    assert any("лист" in n.lower() for n in names)
    assert any("круг" in n.lower() for n in names)


def test_no_api_warning_in_result(agent_no_api):
    req = _request()
    result = agent_no_api.procure(req)
    assert len(result.warnings) > 0
    assert any("api" in w.lower() or "ключ" in w.lower() for w in result.warnings)


def test_summary_not_empty(agent_no_api):
    req = _request()
    result = agent_no_api.procure(req)
    assert len(result.agent_summary) > 20
    print(f"\n  summary: {result.agent_summary}")


def test_result_fields_populated(agent_no_api):
    req = _request()
    result = agent_no_api.procure(req)
    assert result.mk_number == "01-04.26"
    assert result.product_name == "Уплотнение П4.05.00.280"
    assert result.region == "Калининград"
    assert result.materials_to_purchase == req.materials


# ---------------------------------------------------------------------------
# Тесты endpoint'а POST /api/mk/procure
# ---------------------------------------------------------------------------

def test_procure_endpoint_ok():
    payload = _request().model_dump()
    resp = client.post("/api/mk/procure", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["mk_number"] == "01-04.26"
    assert isinstance(data["rfq_letters"], list)
    assert len(data["rfq_letters"]) >= 1
    print(f"\n  rfq_letters: {len(data['rfq_letters'])}, "
          f"suppliers: {len(data['supplier_candidates'])}")


def test_procure_endpoint_rfq_structure():
    payload = _request().model_dump()
    resp = client.post("/api/mk/procure", json=payload)
    data = resp.json()
    for rfq in data["rfq_letters"]:
        assert "supplier_name" in rfq
        assert "subject" in rfq
        assert "body" in rfq
        assert rfq["body"] != ""


def test_procure_endpoint_empty_materials():
    payload = _request(materials=[]).model_dump()
    resp = client.post("/api/mk/procure", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["rfq_letters"] == []
    assert data["supplier_candidates"] == []


def test_procure_endpoint_summary():
    payload = _request().model_dump()
    resp = client.post("/api/mk/procure", json=payload)
    data = resp.json()
    assert data["agent_summary"] != ""
