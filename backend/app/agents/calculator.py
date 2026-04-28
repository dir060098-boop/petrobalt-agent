"""
Агент-Расчётчик МК.

Детерминированный расчёт себестоимости и BOM.
Не требует Claude API — вся логика математическая.

Ключевые формулы:
  qty_required    = qty_per_unit × quantity × waste_factor
  cost            = qty_required × unit_price
  qty_to_purchase = max(qty_required - qty_in_stock, 0)

Коэффициенты отхода по умолчанию (если не заданы вручную):
  Лист/лента/полоса      → 1.15  (15% при раскрое)
  Труба/пруток/круг      → 1.05  (5% при резке)
  Резина/уплотнение      → 1.10  (10% при вырубке)
  Прочее                 → 1.00  (без отхода)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from app.schemas.calculator_schema import (
    CalculatorRequest,
    CalculatorResponse,
    MaterialInput,
    MaterialResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Правила коэффициентов отхода (по ключевым словам в названии материала)
# ---------------------------------------------------------------------------

_WASTE_RULES: List[Tuple[List[str], float, str]] = [
    # (ключевые_слова, коэффициент, описание)
    (["лист", "листовой", "лента", "полоса", "штрипс"],          1.15, "раскрой листа"),
    (["труб", "трубк"],                                            1.05, "резка трубы"),
    (["пруток", "круг", "шестигран", "квадрат", "профил"],        1.05, "резка проката"),
    (["резин", "уплотн", "прокладк", "сальник", "манжет"],        1.10, "вырубка резины"),
    (["проволок", "канат", "трос"],                                1.03, "резка проволоки"),
    (["порошок", "паст", "мастик", "грунт", "краск", "эмал"],     1.05, "технол. потери"),
    (["растворит", "сольвент", "масл", "смазк"],                  1.10, "технол. потери жидк."),
]

_DEFAULT_WASTE_FACTOR = 1.00


def _get_waste_factor(name: str, explicit: Optional[float]) -> Tuple[float, str]:
    """
    Определяет коэффициент отхода для материала.
    Возвращает (коэффициент, источник).
    """
    if explicit is not None:
        if explicit < 1.0:
            logger.warning("waste_factor=%s < 1.0 для '%s' — использован 1.0", explicit, name)
            return 1.0, "manual"
        return explicit, "manual"

    name_lower = name.lower()
    for keywords, factor, _ in _WASTE_RULES:
        if any(kw in name_lower for kw in keywords):
            return factor, "rule"

    return _DEFAULT_WASTE_FACTOR, "default"


def _round2(v: float) -> float:
    return round(v, 4)


# ---------------------------------------------------------------------------
# Основной класс
# ---------------------------------------------------------------------------

class CalculatorAgent:
    """
    Агент-Расчётчик — детерминированный, без AI.
    Рассчитывает BOM, себестоимость, потребность в закупке.
    """

    def calculate(self, request: CalculatorRequest) -> CalculatorResponse:
        """Выполняет расчёт по запросу."""
        warnings: List[str] = []
        results: List[MaterialResult] = []

        quantity = request.quantity
        if quantity <= 0:
            raise ValueError(f"Количество изделий должно быть > 0, получено: {quantity}")

        for mat in request.materials:
            result = self._calculate_material(mat, quantity, request.default_waste_factor, warnings)
            results.append(result)

        # Итоговые показатели
        all_have_price = all(m.unit_price is not None for m in request.materials)
        total_cost: Optional[float] = None
        if all_have_price and results:
            total_cost = _round2(sum(r.cost or 0.0 for r in results))

        needs_purchase = any(r.qty_to_purchase > 0 for r in results)
        total_qty_to_purchase = sum(r.qty_to_purchase for r in results)

        snapshot_at = datetime.now(timezone.utc).isoformat()

        # Резюме
        summary = self._build_summary(
            request, results, total_cost, needs_purchase, warnings,
        )

        logger.info(
            "CalculatorAgent: mk=%s, qty=%s, materials=%d, total_cost=%s, "
            "needs_purchase=%s, warnings=%d",
            request.mk_number, quantity, len(results),
            total_cost, needs_purchase, len(warnings),
        )

        return CalculatorResponse(
            mk_number=request.mk_number,
            article=request.article,
            product_name=request.product_name,
            quantity=quantity,
            materials=results,
            total_cost=total_cost,
            total_qty_to_purchase=_round2(total_qty_to_purchase),
            has_prices=all_have_price,
            needs_purchase=needs_purchase,
            snapshot_at=snapshot_at,
            agent_summary=summary,
            warnings=warnings,
        )

    # -----------------------------------------------------------------------
    # Вспомогательные методы
    # -----------------------------------------------------------------------

    def _calculate_material(
        self,
        mat: MaterialInput,
        quantity: float,
        default_waste_override: Optional[float],
        warnings: List[str],
    ) -> MaterialResult:
        """Рассчитывает показатели по одному материалу."""

        # Коэффициент отхода
        explicit = mat.waste_factor if mat.waste_factor is not None else default_waste_override
        waste_factor, wf_source = _get_waste_factor(mat.name, explicit)

        # qty_required = qty_per_unit × quantity × waste_factor
        qty_required = _round2(mat.qty_per_unit * quantity * waste_factor)

        # Сравниваем с qty_issued (отпущено со склада) — предупреждение при расхождении
        if mat.qty_issued is not None:
            diff_pct = abs(qty_required - mat.qty_issued) / max(mat.qty_issued, 0.001) * 100
            if diff_pct > 20:
                warnings.append(
                    f"«{mat.name}»: расчётное кол-во {qty_required} {mat.unit} "
                    f"отличается от отпущенного {mat.qty_issued} {mat.unit} "
                    f"на {diff_pct:.0f}%"
                )

        # Себестоимость
        cost: Optional[float] = None
        if mat.unit_price is not None:
            if mat.unit_price < 0:
                warnings.append(f"«{mat.name}»: цена отрицательная ({mat.unit_price}) — игнорируется")
            else:
                cost = _round2(qty_required * mat.unit_price)

        # Остаток и потребность в закупке
        qty_in_stock = mat.qty_in_stock if mat.qty_in_stock is not None else 0.0
        qty_to_purchase = _round2(max(qty_required - qty_in_stock, 0.0))

        return MaterialResult(
            name=mat.name,
            unit=mat.unit,
            qty_per_unit=mat.qty_per_unit,
            waste_factor=waste_factor,
            waste_factor_source=wf_source,
            qty_required=qty_required,
            qty_issued=mat.qty_issued,
            unit_price=mat.unit_price,
            cost=cost,
            qty_in_stock=qty_in_stock,
            qty_to_purchase=qty_to_purchase,
        )

    def _build_summary(
        self,
        request: CalculatorRequest,
        results: List[MaterialResult],
        total_cost: Optional[float],
        needs_purchase: bool,
        warnings: List[str],
    ) -> str:
        lines = [
            f"Расчёт МК {request.mk_number} — «{request.product_name}», "
            f"{request.quantity} шт.",
            f"Обработано материалов: {len(results)}.",
        ]

        if total_cost is not None:
            lines.append(f"Общая себестоимость материалов: {total_cost:,.2f} руб.")
        else:
            missing_prices = sum(1 for r in results if r.unit_price is None)
            lines.append(
                f"Себестоимость не рассчитана — отсутствуют цены "
                f"по {missing_prices} из {len(results)} позиций."
            )

        if needs_purchase:
            to_buy = [r for r in results if r.qty_to_purchase > 0]
            lines.append(
                f"Требуется закупка по {len(to_buy)} позициям "
                f"(покрытие склада недостаточно)."
            )
        else:
            lines.append("Склад покрывает всю потребность — закупка не требуется.")

        if warnings:
            lines.append(f"Предупреждения: {len(warnings)}. Проверьте данные.")

        return " ".join(lines)
