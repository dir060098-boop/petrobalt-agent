"""
Схемы для агента-Расчётчика.

Поток:
  1. Клиент передаёт подтверждённые данные МК + плановые материалы
     + опциональные цены + остатки склада
  2. Агент рассчитывает:
       qty_required  = qty_per_unit × quantity × waste_factor
       cost          = qty_required × unit_price
       qty_to_purchase = max(qty_required - qty_in_stock, 0)
  3. Возвращает BOM, себестоимость, список к закупке
  4. snapshot_at фиксирует момент расчёта (цены не пересчитываются)
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Входные данные
# ---------------------------------------------------------------------------

class MaterialInput(BaseModel):
    """Один материал на входе расчётчика."""
    name: str
    unit: str
    qty_per_unit: float          # из МК: количество на 1 изделие
    qty_issued: Optional[float] = None  # отпущено со склада (из МК, для сверки)

    # Экономика — заполняется из БД или вводится вручную
    unit_price: Optional[float] = None      # цена за единицу, руб.
    qty_in_stock: Optional[float] = None    # текущий остаток на складе

    # Коэффициент отхода — если None, агент определит по названию материала
    waste_factor: Optional[float] = None


class CalculatorRequest(BaseModel):
    """Запрос на расчёт себестоимости МК."""
    mk_number: str
    article: str
    product_name: str
    quantity: float              # количество изделий из МК

    materials: List[MaterialInput]

    # Опционально: переопределить дефолтный коэффициент отхода для всего МК
    default_waste_factor: Optional[float] = None

    # Ссылка на route_card в БД (для сохранения purchase_request)
    route_card_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Выходные данные
# ---------------------------------------------------------------------------

class MaterialResult(BaseModel):
    """Расчётный результат по одному материалу."""
    name: str
    unit: str

    qty_per_unit: float          # на 1 изделие (из МК)
    waste_factor: float          # применённый коэффициент
    qty_required: float          # = qty_per_unit × quantity × waste_factor
    qty_issued: Optional[float] = None  # из МК

    unit_price: Optional[float] = None
    cost: Optional[float] = None        # = qty_required × unit_price

    qty_in_stock: float = 0.0           # остаток на складе
    qty_to_purchase: float = 0.0        # = max(qty_required - qty_in_stock, 0)

    # Откуда взят коэффициент
    waste_factor_source: str = "default"  # "manual" | "rule" | "default"


class CalculatorResponse(BaseModel):
    """Результат расчёта."""
    mk_number: str
    article: str
    product_name: str
    quantity: float

    materials: List[MaterialResult]

    # Итоги
    total_cost: Optional[float] = None      # None если нет всех цен
    total_qty_to_purchase: float = 0.0      # суммарный объём закупки (в разных ед.)
    has_prices: bool = False                # True если все цены заполнены
    needs_purchase: bool = False            # True если qty_to_purchase > 0 хоть по одному

    # Snapshot — момент расчёта (цены зафиксированы, не пересчитываются)
    snapshot_at: str = ""

    # Резюме
    agent_summary: str = ""
    warnings: List[str] = []
