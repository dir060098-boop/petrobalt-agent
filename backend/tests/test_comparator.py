"""
Тесты агента-Сравнителя КП (weighted scoring).
Запуск: python -m pytest backend/tests/test_comparator.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.agents.comparator import ComparatorAgent, _compare_one, _normalize_prices, _normalize_lead_times
from app.schemas.comparator_schema import (
    CompareBatchRequest,
    CompareRequest,
    QuoteItem,
    SupplierQuote,
)

client = TestClient(app)
agent = ComparatorAgent()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _quote(
    name: str,
    price: float,
    lead_days: int,
    verified: bool = False,
    has_vat: bool = True,
    stype: str = "distributor",
    material: str = "Лист г/к 10*1500*6000",
) -> SupplierQuote:
    return SupplierQuote(
        supplier_name=name,
        supplier_type=stype,
        is_verified=verified,
        has_vat=has_vat,
        lead_time_days=lead_days,
        items=[QuoteItem(
            material_name=material,
            unit="кг",
            quantity_requested=7.85,
            unit_price=price,
        )],
    )


def _req(quotes: list, material="Лист г/к 10*1500*6000") -> CompareRequest:
    return CompareRequest(
        mk_number="01-04.26",
        material_name=material,
        quantity_required=7.85,
        quotes=quotes,
    )


# ---------------------------------------------------------------------------
# Тесты нормализации
# ---------------------------------------------------------------------------

def test_normalize_prices_best_gets_one():
    quotes = [
        _quote("A", price=80.0, lead_days=10),
        _quote("B", price=100.0, lead_days=10),
        _quote("C", price=120.0, lead_days=10),
    ]
    scores = _normalize_prices(quotes, "Лист г/к 10*1500*6000")
    assert scores["A"] == 1.0   # минимальная цена → максимальный балл
    assert scores["C"] == 0.0   # максимальная цена → минимальный балл
    assert 0.0 < scores["B"] < 1.0


def test_normalize_prices_equal_all_one():
    quotes = [_quote("A", 100.0, 10), _quote("B", 100.0, 10)]
    scores = _normalize_prices(quotes, "Лист г/к 10*1500*6000")
    assert scores["A"] == 1.0
    assert scores["B"] == 1.0


def test_normalize_lead_times_shortest_gets_one():
    quotes = [
        _quote("Fast", 100.0, lead_days=5),
        _quote("Medium", 100.0, lead_days=15),
        _quote("Slow", 100.0, lead_days=30),
    ]
    scores = _normalize_lead_times(quotes)
    assert scores["Fast"]   == 1.0
    assert scores["Slow"]   == 0.0
    assert 0.0 < scores["Medium"] < 1.0


# ---------------------------------------------------------------------------
# Тесты scoring
# ---------------------------------------------------------------------------

def test_lower_price_wins_when_equal_else():
    """При равных остальных параметрах — победит тот, у кого ниже цена."""
    quotes = [
        _quote("Cheap",     price=80.0,  lead_days=10),
        _quote("Expensive", price=120.0, lead_days=10),
    ]
    result = _compare_one(_req(quotes))
    assert result.winner == "Cheap"
    assert result.scored_quotes[0].supplier_name == "Cheap"
    assert result.scored_quotes[0].rank == 1


def test_verified_supplier_beats_unverified_at_same_price():
    """Верифицированный поставщик с той же ценой должен получить выше score."""
    q_verified   = _quote("Verified",   price=100.0, lead_days=10, verified=True)
    q_unverified = _quote("Unverified", price=100.0, lead_days=10, verified=False)
    result = _compare_one(_req([q_verified, q_unverified]))
    v  = next(q for q in result.scored_quotes if q.supplier_name == "Verified")
    uv = next(q for q in result.scored_quotes if q.supplier_name == "Unverified")
    assert v.scores.total > uv.scores.total


def test_manufacturer_beats_trader_at_same_price_and_delivery():
    q_mfr    = _quote("Mfr",    100.0, 10, stype="manufacturer")
    q_trader = _quote("Trader", 100.0, 10, stype="trader")
    result = _compare_one(_req([q_mfr, q_trader]))
    assert result.winner == "Mfr"


def test_no_vat_penalized():
    q_vat    = _quote("WithVAT",    100.0, 10, has_vat=True)
    q_no_vat = _quote("NoVAT",      100.0, 10, has_vat=False)
    result = _compare_one(_req([q_vat, q_no_vat]))
    vat_score    = next(q for q in result.scored_quotes if q.supplier_name == "WithVAT")
    no_vat_score = next(q for q in result.scored_quotes if q.supplier_name == "NoVAT")
    assert vat_score.scores.vat > no_vat_score.scores.vat


def test_score_total_in_0_1_range():
    quotes = [
        _quote("A", 90.0,  7,  verified=True,  has_vat=True,  stype="manufacturer"),
        _quote("B", 110.0, 20, verified=False, has_vat=False, stype="trader"),
    ]
    result = _compare_one(_req(quotes))
    for sq in result.scored_quotes:
        assert 0.0 <= sq.scores.total <= 1.0


def test_rank_order():
    """Ранги идут 1, 2, 3 строго."""
    quotes = [_quote(f"S{i}", float(80 + i*10), lead_days=10) for i in range(3)]
    result = _compare_one(_req(quotes))
    ranks = [sq.rank for sq in result.scored_quotes]
    assert ranks == [1, 2, 3]


def test_recommendation_labels():
    """Первый — recommended, второй близкий — alternative, остальные — not_recommended."""
    # Близкие цены → второй может быть alternative
    quotes = [
        _quote("Best",  80.0,  5),
        _quote("Good",  85.0,  5),   # в пределах 85% от лучшего
        _quote("Worst", 200.0, 30),
    ]
    result = _compare_one(_req(quotes))
    assert result.scored_quotes[0].recommendation == "recommended"
    assert result.scored_quotes[-1].recommendation == "not_recommended"


def test_price_spread_calculated():
    quotes = [_quote("A", 80.0, 10), _quote("B", 120.0, 10)]
    result = _compare_one(_req(quotes))
    expected = round((120 - 80) / 80 * 100, 1)
    assert result.price_spread_pct == expected


def test_single_quote_no_crash():
    """Один поставщик → не падаем, score = 1.0 по всем нормализованным."""
    result = _compare_one(_req([_quote("Only", 100.0, 10)]))
    assert len(result.scored_quotes) == 1
    assert result.winner == "Only"
    assert result.scored_quotes[0].scores.price == 1.0


def test_empty_quotes_returns_empty():
    result = _compare_one(_req([]))
    assert result.winner is None
    assert result.scored_quotes == []


# ---------------------------------------------------------------------------
# Тесты batch-сравнения
# ---------------------------------------------------------------------------

def test_batch_two_materials():
    req = CompareBatchRequest(
        mk_number="01-04.26",
        items=[
            _req(
                [_quote("MetalA", 80.0, 7), _quote("MetalB", 95.0, 14)],
                material="Лист г/к 10*1500*6000",
            ),
            _req(
                [_quote("RubberX", 300.0, 5), _quote("RubberY", 320.0, 3)],
                material="Резиновая смесь 7-В-14",
            ),
        ],
    )
    resp = agent.compare_batch(req)
    assert len(resp.results) == 2
    assert resp.results[0].material_name == "Лист г/к 10*1500*6000"
    assert resp.results[1].material_name == "Резиновая смесь 7-В-14"
    assert resp.overall_summary != ""


def test_batch_warning_one_quote():
    """Предупреждение если меньше 2 КП."""
    req = CompareBatchRequest(
        mk_number="01-04.26",
        items=[_req([_quote("Only", 100.0, 10)])],
    )
    resp = agent.compare_batch(req)
    assert any("минимум 2" in w for w in resp.warnings)


# ---------------------------------------------------------------------------
# Тесты endpoint'а POST /api/mk/compare
# ---------------------------------------------------------------------------

def test_compare_endpoint_ok():
    payload = CompareBatchRequest(
        mk_number="01-04.26",
        items=[
            _req([
                _quote("MetalTorg",   85.0, 7,  verified=True,  stype="manufacturer"),
                _quote("MetalSnab",  100.0, 14, verified=False, stype="distributor"),
                _quote("Spektr",     110.0, 21, verified=False, stype="trader"),
            ]),
        ],
    ).model_dump()
    resp = client.post("/api/mk/compare", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["mk_number"] == "01-04.26"
    assert len(data["results"]) == 1
    assert data["results"][0]["winner"] == "MetalTorg"
    print(f"\n  winner: {data['results'][0]['winner']}")
    print(f"  summary: {data['results'][0]['summary']}")


def test_compare_endpoint_scores_structure():
    payload = CompareBatchRequest(
        mk_number="01-04.26",
        items=[_req([_quote("A", 90.0, 10), _quote("B", 110.0, 20)])],
    ).model_dump()
    resp = client.post("/api/mk/compare", json=payload)
    data = resp.json()
    for sq in data["results"][0]["scored_quotes"]:
        assert "rank" in sq
        assert "scores" in sq
        assert "recommendation" in sq
        scores = sq["scores"]
        assert all(k in scores for k in ["price", "lead_time", "verification", "vat", "supplier_type", "total"])


def test_compare_endpoint_custom_weights():
    """Если задать weight_price=1.0 — победит только самая дешёвая."""
    payload = CompareBatchRequest(
        mk_number="01-04.26",
        items=[CompareRequest(
            mk_number="01-04.26",
            material_name="Лист г/к 10*1500*6000",
            quantity_required=7.85,
            quotes=[
                _quote("Cheap",     80.0,  30, verified=False, stype="trader"),   # дешевле
                _quote("Expensive", 120.0, 5,  verified=True,  stype="manufacturer"),
            ],
            weight_price=1.0,
            weight_lead_time=0.0,
            weight_verification=0.0,
            weight_vat=0.0,
            weight_type=0.0,
        )],
    ).model_dump()
    resp = client.post("/api/mk/compare", json=payload)
    data = resp.json()
    assert data["results"][0]["winner"] == "Cheap"


def test_compare_endpoint_overall_summary():
    payload = CompareBatchRequest(
        mk_number="01-04.26",
        items=[_req([_quote("A", 90.0, 10), _quote("B", 110.0, 20)])],
    ).model_dump()
    resp = client.post("/api/mk/compare", json=payload)
    data = resp.json()
    assert data["overall_summary"] != ""
