"""
Интеграционный тест endpoint'а POST /api/mk/parse.
Запуск: python -m pytest backend/tests/test_mk_endpoint.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient

from app.main import app

MK_FILE = Path(
    "/Users/dinararisalieva/Desktop/Coworking/Расчет материалов и поиск поставщиков"
    "/Уплотнение/МК 01-04.26(1.(П4.05.00.280)1.4.1 - ЮПБ(испытания) (1).pdf"
)

client = TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def response():
    with open(MK_FILE, "rb") as f:
        resp = client.post(
            "/api/mk/parse",
            files={"file": ("МК 01-04.26.pdf", f, "application/pdf")},
        )
    return resp


@pytest.fixture(scope="module")
def data(response):
    return response.json()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_status_200(response):
    assert response.status_code == 200, response.text


def test_success_flag(data):
    assert data["success"] is True


def test_confidence(data):
    print(f"\n  confidence: {data['confidence']}")
    assert data["confidence"] >= 0.6


def test_mk_number(data):
    assert data["mk_number"]["status"] == "extracted"
    assert data["mk_number"]["value"] == "01-04.26"
    print(f"\n  mk_number: {data['mk_number']['value']}")


def test_article(data):
    assert data["article"]["status"] == "extracted"
    print(f"\n  article: {data['article']['value']}")


def test_product_name(data):
    assert data["product_name"]["status"] == "extracted"
    assert data["product_name"]["value"] is not None
    print(f"\n  product_name: {data['product_name']['value']}")


def test_quantity(data):
    assert data["quantity"]["status"] == "extracted"
    assert data["quantity"]["value"] == 4.0
    print(f"\n  quantity: {data['quantity']['value']}")


def test_date_start(data):
    assert data["date_start"]["status"] == "extracted"
    print(f"\n  date_start: {data['date_start']['value']}")


def test_planned_materials(data):
    materials = data["planned_materials"]
    assert len(materials) > 0
    print(f"\n  planned_materials: {len(materials)}")
    for m in materials:
        print(f"    - {m['name']['value']} | qty_per_unit={m['qty_per_unit']['value']} {m['unit']['value']}")


def test_actual_materials(data):
    materials = data["actual_materials"]
    assert len(materials) > 0
    print(f"\n  actual_materials: {len(materials)}")


def test_no_parse_errors(data):
    if data["parse_errors"]:
        print(f"\n  parse_errors: {data['parse_errors']}")
    assert data["parse_errors"] == []


def test_no_missing_critical(data):
    print(f"\n  missing_critical: {data['missing_critical_fields']}")
    assert data["missing_critical_fields"] == []


def test_field_statuses_endpoint():
    resp = client.get("/api/mk/fields")
    assert resp.status_code == 200
    body = resp.json()
    assert "statuses" in body
    assert "critical_fields" in body
    assert "mk_number" in body["critical_fields"]


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Негативные тесты
# ---------------------------------------------------------------------------

def test_wrong_file_type():
    resp = client.post(
        "/api/mk/parse",
        files={"file": ("document.txt", b"not a pdf", "text/plain")},
    )
    assert resp.status_code == 422


def test_empty_file():
    resp = client.post(
        "/api/mk/parse",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert resp.status_code == 422
