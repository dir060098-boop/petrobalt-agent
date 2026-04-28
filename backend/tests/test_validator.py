"""
Тесты агента-Проверяющего МК (детерминированная часть — без Claude API).
Запуск: python -m pytest backend/tests/test_validator.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.agents.validator import ValidatorAgent
from app.schemas.validator_schema import (
    FieldConfirmation,
    IssueSeverity,
    ValidatorRequest,
)

client = TestClient(app)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _full_request(**overrides) -> ValidatorRequest:
    """Создаёт валидный запрос — все критичные поля заполнены."""
    base = dict(
        mk_number="01-04.26",
        article="1.(П4.05.00.280)1.4.1",
        product_name="Уплотнение П4.05.00.280",
        quantity=4.0,
        quantity_unit="шт",
        date_start="14.4.26",
        date_end="14.04.2026",
        created_by="Герасимов А.С.",
        verified_by="Кирилюк А.С.",
        field_statuses={
            "mk_number": "extracted", "article": "extracted",
            "product_name": "extracted", "quantity": "extracted",
            "quantity_unit": "extracted", "date_start": "extracted",
            "date_end": "extracted", "created_by": "extracted",
            "verified_by": "extracted",
        },
        planned_materials_count=4,
        actual_materials_count=4,
        operations_count=0,
        parse_errors=[],
        confidence=1.0,
    )
    base.update(overrides)
    return ValidatorRequest(**base)


@pytest.fixture(scope="module")
def agent():
    # Без API ключа — только детерминированная проверка
    return ValidatorAgent(api_key="")


# ---------------------------------------------------------------------------
# Тесты детерминированной проверки
# ---------------------------------------------------------------------------

def test_all_fields_present_is_ready(agent):
    req = _full_request()
    result = agent.validate(req)
    assert result.ready_for_calculation is True
    assert result.status == "ready"
    assert result.missing_critical == []


def test_missing_mk_number_blocks(agent):
    req = _full_request(mk_number=None, field_statuses={
        "mk_number": "missing", "article": "extracted",
        "product_name": "extracted", "quantity": "extracted",
        "date_start": "extracted",
    })
    result = agent.validate(req)
    assert result.ready_for_calculation is False
    assert "mk_number" in result.missing_critical
    critical = [i for i in result.issues if i.severity == IssueSeverity.critical]
    assert any(i.field == "mk_number" for i in critical)


def test_missing_quantity_blocks(agent):
    req = _full_request(quantity=None, field_statuses={
        "mk_number": "extracted", "article": "extracted",
        "product_name": "extracted", "quantity": "missing",
        "date_start": "extracted",
    })
    result = agent.validate(req)
    assert result.ready_for_calculation is False
    assert "quantity" in result.missing_critical


def test_negative_quantity_is_critical(agent):
    req = _full_request(quantity=-5.0)
    result = agent.validate(req)
    assert result.ready_for_calculation is False
    qty_issues = [i for i in result.issues if i.field == "quantity" and i.severity == IssueSeverity.critical]
    assert len(qty_issues) > 0


def test_bad_mk_number_format_is_warning(agent):
    req = _full_request(mk_number="WRONG-FORMAT")
    result = agent.validate(req)
    # warning, не critical — не блокирует
    mk_issues = [i for i in result.issues if i.field == "mk_number"]
    assert any(i.severity == IssueSeverity.warning for i in mk_issues)
    # но готовность зависит только от critical — может быть готово
    assert result.missing_critical == []  # поле есть, просто формат кривой


def test_no_planned_materials_is_warning(agent):
    req = _full_request(planned_materials_count=0)
    result = agent.validate(req)
    mat_issues = [i for i in result.issues if "material" in i.field]
    assert any(i.severity == IssueSeverity.warning for i in mat_issues)
    # не блокирует расчёт
    assert result.ready_for_calculation is True


def test_parse_errors_become_warnings(agent):
    req = _full_request(parse_errors=["Table parse error: some error"])
    result = agent.validate(req)
    general_issues = [i for i in result.issues if i.field == "general"]
    assert len(general_issues) > 0


# ---------------------------------------------------------------------------
# Тесты применения подтверждений пользователя
# ---------------------------------------------------------------------------

def test_confirmation_changes_status_to_manual(agent):
    """Пользователь вводит quantity вручную (было missing)."""
    req = _full_request(
        quantity=None,
        field_statuses={"mk_number": "extracted", "article": "extracted",
                        "product_name": "extracted", "quantity": "missing",
                        "date_start": "extracted"},
        confirmations=[FieldConfirmation(field_name="quantity", value=4.0)],
    )
    result = agent.validate(req)
    assert result.validated_fields["quantity"].status == "manual"
    assert result.validated_fields["quantity"].value == 4.0
    assert result.ready_for_calculation is True


def test_confirmation_changes_status_to_confirmed(agent):
    """Пользователь подтверждает extracted поле."""
    req = _full_request(
        confirmations=[FieldConfirmation(field_name="mk_number", value="01-04.26")],
    )
    result = agent.validate(req)
    assert result.validated_fields["mk_number"].status == "confirmed"


def test_multiple_missing_fields_all_reported(agent):
    req = _full_request(
        mk_number=None,
        article=None,
        quantity=None,
        field_statuses={
            "mk_number": "missing", "article": "missing",
            "product_name": "extracted", "quantity": "missing",
            "date_start": "extracted",
        },
    )
    result = agent.validate(req)
    assert set(result.missing_critical) >= {"mk_number", "article", "quantity"}
    assert result.ready_for_calculation is False


# ---------------------------------------------------------------------------
# Тесты endpoint'а POST /api/mk/validate
# ---------------------------------------------------------------------------

def test_validate_endpoint_ready():
    payload = _full_request().model_dump()
    resp = client.post("/api/mk/validate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready_for_calculation"] is True
    assert data["status"] == "ready"
    assert data["missing_critical"] == []


def test_validate_endpoint_needs_input():
    payload = _full_request(
        mk_number=None,
        field_statuses={"mk_number": "missing", "article": "extracted",
                        "product_name": "extracted", "quantity": "extracted",
                        "date_start": "extracted"},
    ).model_dump()
    resp = client.post("/api/mk/validate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready_for_calculation"] is False
    assert data["status"] == "needs_input"
    assert "mk_number" in data["missing_critical"]
    assert data["blocked_reason"] is not None


def test_validate_endpoint_with_confirmation():
    """Пользователь вводит отсутствующее количество — МК становится готовой."""
    payload = _full_request(
        quantity=None,
        field_statuses={"mk_number": "extracted", "article": "extracted",
                        "product_name": "extracted", "quantity": "missing",
                        "date_start": "extracted"},
        confirmations=[{"field_name": "quantity", "value": 4.0}],
    ).model_dump()
    resp = client.post("/api/mk/validate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready_for_calculation"] is True
    assert data["validated_fields"]["quantity"]["status"] == "manual"
    assert data["validated_fields"]["quantity"]["value"] == 4.0


def test_validate_endpoint_summary_not_empty():
    payload = _full_request().model_dump()
    resp = client.post("/api/mk/validate", json=payload)
    data = resp.json()
    assert data["agent_summary"]
    assert len(data["agent_summary"]) > 10
    print(f"\n  agent_summary: {data['agent_summary']}")
