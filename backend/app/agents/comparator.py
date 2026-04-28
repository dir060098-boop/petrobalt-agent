"""
Агент-Сравнитель коммерческих предложений.

Детерминированный weighted scoring — Claude не нужен.
Каждый критерий нормализуется в [0..1] внутри группы предложений.

Формула:
  score_total = price*w_p + lead_time*w_l + verification*w_v + vat*w_vat + type*w_t

Нормализация:
  price      — min-max (меньше цена → выше балл)
  lead_time  — min-max (меньше дней → выше балл)
  verification — 1.0 если в БД, 0.0 если из веба
  vat          — 1.0 если с НДС, 0.3 если без (без НДС иногда выгодно, но рискованнее)
  type         — manufacturer=1.0, distributor=0.7, trader=0.4, unknown=0.5
"""

from __future__ import annotations

import logging
from typing import Dict, List, Tuple

from app.schemas.comparator_schema import (
    CompareBatchRequest,
    CompareBatchResponse,
    CompareRequest,
    CompareResult,
    ScoreBreakdown,
    ScoredQuote,
    SupplierQuote,
)

logger = logging.getLogger(__name__)

# Оценки типа поставщика
_TYPE_SCORES: Dict[str, float] = {
    "manufacturer": 1.00,
    "distributor":  0.70,
    "trader":       0.40,
    "unknown":      0.50,
}

# Оценка наличия НДС
_VAT_SCORE_YES = 1.0
_VAT_SCORE_NO  = 0.3


# ---------------------------------------------------------------------------
# Нормализация
# ---------------------------------------------------------------------------

def _minmax(value: float, mn: float, mx: float) -> float:
    """Min-max нормализация. Если диапазон = 0 → все одинаковы → 1.0."""
    if mx == mn:
        return 1.0
    return (value - mn) / (mx - mn)


def _normalize_prices(quotes: List[SupplierQuote], material_name: str) -> Dict[str, float]:
    """
    Нормализует цены: меньшая цена → более высокий балл.
    Возвращает {supplier_name: price_score}.
    """
    prices: Dict[str, float] = {}
    for q in quotes:
        for item in q.items:
            if item.material_name == material_name:
                prices[q.supplier_name] = item.unit_price
                break

    if not prices:
        return {q.supplier_name: 1.0 for q in quotes}

    mn = min(prices.values())
    mx = max(prices.values())

    # Если все цены одинаковые — все получают максимальный балл
    if mn == mx:
        return {name: 1.0 for name in prices}

    return {
        name: round(1.0 - _minmax(price, mn, mx), 4)
        # инвертируем: меньше цена → выше score
        for name, price in prices.items()
    }


def _normalize_lead_times(quotes: List[SupplierQuote]) -> Dict[str, float]:
    """
    Нормализует сроки: меньший срок → более высокий балл.
    """
    days = {q.supplier_name: q.lead_time_days for q in quotes}
    mn = min(days.values())
    mx = max(days.values())

    # Если все сроки одинаковые — все получают максимальный балл
    if mn == mx:
        return {name: 1.0 for name in days}

    return {
        name: round(1.0 - _minmax(d, mn, mx), 4)
        for name, d in days.items()
    }


# ---------------------------------------------------------------------------
# Единичное сравнение (один материал)
# ---------------------------------------------------------------------------

def _compare_one(req: CompareRequest) -> CompareResult:
    """Сравнивает КП по одному материалу."""
    quotes = req.quotes
    if not quotes:
        return CompareResult(
            material_name=req.material_name,
            quantity_required=req.quantity_required,
            quotes_count=0,
            scored_quotes=[],
            winner=None,
            price_spread_pct=0.0,
            weights_used={},
            summary="Нет предложений для сравнения.",
        )

    # Нормализация
    price_scores   = _normalize_prices(quotes, req.material_name)
    lt_scores      = _normalize_lead_times(quotes)

    weights = {
        "price":        req.weight_price,
        "lead_time":    req.weight_lead_time,
        "verification": req.weight_verification,
        "vat":          req.weight_vat,
        "type":         req.weight_type,
    }

    scored: List[Tuple[float, ScoredQuote]] = []

    for q in quotes:
        # Получаем цену за ед. и итого для этого материала
        unit_price  = 0.0
        total_price = 0.0
        for item in q.items:
            if item.material_name == req.material_name:
                unit_price  = item.unit_price
                total_price = item.total_price
                break

        s_price  = price_scores.get(q.supplier_name, 1.0)
        s_lt     = lt_scores.get(q.supplier_name, 1.0)
        s_verif  = 1.0 if q.is_verified else 0.0
        s_vat    = _VAT_SCORE_YES if q.has_vat else _VAT_SCORE_NO
        s_type   = _TYPE_SCORES.get(q.supplier_type, 0.5)

        total = round(
            s_price  * req.weight_price +
            s_lt     * req.weight_lead_time +
            s_verif  * req.weight_verification +
            s_vat    * req.weight_vat +
            s_type   * req.weight_type,
            4,
        )

        breakdown = ScoreBreakdown(
            price=s_price,
            lead_time=s_lt,
            verification=s_verif,
            vat=s_vat,
            supplier_type=s_type,
            total=total,
        )

        scored.append((total, ScoredQuote(
            rank=0,           # заполним после сортировки
            supplier_name=q.supplier_name,
            supplier_type=q.supplier_type,
            is_verified=q.is_verified,
            has_vat=q.has_vat,
            lead_time_days=q.lead_time_days,
            unit_price=unit_price,
            total_price=total_price,
            scores=breakdown,
            recommendation="",  # заполним после
        )))

    # Сортируем по total desc
    scored.sort(key=lambda x: x[0], reverse=True)

    # Присваиваем ранги и рекомендации
    result_quotes: List[ScoredQuote] = []
    for rank, (total, sq) in enumerate(scored, start=1):
        if rank == 1:
            rec = "recommended"
        elif rank == 2 and total >= scored[0][0] * 0.85:
            rec = "alternative"
        else:
            rec = "not_recommended"
        sq.rank = rank
        sq.recommendation = rec
        result_quotes.append(sq)

    winner = result_quotes[0].supplier_name if result_quotes else None

    # Разброс цен
    prices_list = [sq.unit_price for sq in result_quotes if sq.unit_price > 0]
    spread_pct = 0.0
    if len(prices_list) >= 2:
        spread_pct = round(
            (max(prices_list) - min(prices_list)) / min(prices_list) * 100, 1
        )

    summary = _material_summary(req.material_name, result_quotes, spread_pct)

    logger.debug(
        "Comparator [%s]: %d quotes, winner=%s, spread=%.1f%%",
        req.material_name, len(quotes), winner, spread_pct,
    )

    return CompareResult(
        material_name=req.material_name,
        quantity_required=req.quantity_required,
        quotes_count=len(quotes),
        scored_quotes=result_quotes,
        winner=winner,
        price_spread_pct=spread_pct,
        weights_used=weights,
        summary=summary,
    )


def _material_summary(
    material: str,
    quotes: List[ScoredQuote],
    spread_pct: float,
) -> str:
    if not quotes:
        return f"«{material}»: предложений нет."

    winner = quotes[0]
    parts = [
        f"«{material}»: {len(quotes)} КП.",
        f"Лучший — {winner.supplier_name} "
        f"({winner.unit_price:.2f} руб/ед., срок {winner.lead_time_days} дн., "
        f"score {winner.scores.total:.2f}).",
    ]
    if spread_pct > 0:
        parts.append(f"Разброс цен: {spread_pct:.1f}%.")
    if len(quotes) >= 2:
        alt = next((q for q in quotes if q.recommendation == "alternative"), None)
        if alt:
            parts.append(f"Альтернатива: {alt.supplier_name} (score {alt.scores.total:.2f}).")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Основной класс
# ---------------------------------------------------------------------------

class ComparatorAgent:
    """
    Агент-Сравнитель коммерческих предложений.
    Детерминированный, не требует API.
    """

    def compare_batch(self, request: CompareBatchRequest) -> CompareBatchResponse:
        """Сравнивает КП по всем материалам в запросе."""
        warnings: List[str] = []
        results: List[CompareResult] = []

        for item in request.items:
            # Валидация весов
            total_weight = round(
                item.weight_price + item.weight_lead_time +
                item.weight_verification + item.weight_vat + item.weight_type,
                4,
            )
            if abs(total_weight - 1.0) > 0.01:
                warnings.append(
                    f"«{item.material_name}»: сумма весов = {total_weight:.2f} ≠ 1.0. "
                    f"Рекомендуется привести к 1.0."
                )

            if len(item.quotes) < 2:
                warnings.append(
                    f"«{item.material_name}»: только {len(item.quotes)} КП — "
                    f"сравнение не даёт смысла, нужно минимум 2."
                )

            results.append(_compare_one(item))

        overall = self._overall_summary(request.mk_number, results)

        logger.info(
            "ComparatorAgent: mk=%s, materials=%d, warnings=%d",
            request.mk_number, len(results), len(warnings),
        )

        return CompareBatchResponse(
            mk_number=request.mk_number,
            results=results,
            overall_summary=overall,
            warnings=warnings,
        )

    def compare_one(self, request: CompareRequest) -> CompareResult:
        """Сравнивает КП по одному материалу (удобный shortcut)."""
        return _compare_one(request)

    # -----------------------------------------------------------------------

    def _overall_summary(self, mk_number: str, results: List[CompareResult]) -> str:
        if not results:
            return f"МК {mk_number}: материалов для сравнения нет."

        winners = [r.winner for r in results if r.winner]
        parts = [f"МК {mk_number}: сравнение завершено по {len(results)} материалам."]

        if winners:
            parts.append(f"Рекомендованные поставщики: {', '.join(set(winners))}.")

        high_spread = [r for r in results if r.price_spread_pct > 30]
        if high_spread:
            names = ", ".join(f"«{r.material_name}»" for r in high_spread)
            parts.append(
                f"Высокий разброс цен (>30%) по: {names} — "
                f"рекомендуется дополнительная проверка."
            )

        return " ".join(parts)
