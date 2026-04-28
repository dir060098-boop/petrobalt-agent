"""
Схемы для агента-Сравнителя коммерческих предложений (КП).

Взвешенный скоринг поставщиков:
  цена       40%   — чем ниже, тем лучше
  срок       25%   — чем короче, тем лучше
  верификация 15%  — поставщик из своей БД vs найден в вебе
  НДС        10%   — с НДС предпочтительнее (можно возместить)
  тип        10%   — производитель > дистрибьютор > трейдер

Все sub-scores нормализованы в диапазон [0.0 … 1.0].
score_total = взвешенная сумма sub-scores.
"""

from __future__ import annotations

from typing import Dict, List, Optional
from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Входные данные
# ---------------------------------------------------------------------------

class QuoteItem(BaseModel):
    """Одна позиция в КП поставщика."""
    material_name: str
    unit: str
    quantity_requested: float      # затребованное количество
    unit_price: float              # цена за единицу (руб.)
    currency: str = "RUB"

    @property
    def total_price(self) -> float:
        return round(self.unit_price * self.quantity_requested, 2)


class SupplierQuote(BaseModel):
    """Полное КП от одного поставщика."""
    supplier_name: str
    supplier_type: str = "unknown"
    # "manufacturer" | "distributor" | "trader" | "unknown"

    is_verified: bool = False      # есть в нашей БД поставщиков
    has_vat: bool = True           # цена включает НДС
    lead_time_days: int = 30       # срок поставки в рабочих днях
    contact: Optional[str] = None
    notes: Optional[str] = None

    items: List[QuoteItem]         # одна или несколько позиций

    @field_validator("supplier_type")
    @classmethod
    def check_type(cls, v: str) -> str:
        allowed = {"manufacturer", "distributor", "trader", "unknown"}
        if v not in allowed:
            raise ValueError(f"supplier_type должен быть одним из {allowed}")
        return v

    @field_validator("lead_time_days")
    @classmethod
    def check_lead_time(cls, v: int) -> int:
        if v < 0:
            raise ValueError("lead_time_days не может быть отрицательным")
        return v


class CompareRequest(BaseModel):
    """Запрос на сравнение КП по одному материалу."""
    mk_number: str
    material_name: str
    quantity_required: float
    quotes: List[SupplierQuote]    # минимум 1, рекомендуется 2+

    # Веса — можно переопределить (сумма должна быть ≈ 1.0)
    weight_price:        float = 0.40
    weight_lead_time:    float = 0.25
    weight_verification: float = 0.15
    weight_vat:          float = 0.10
    weight_type:         float = 0.10


class CompareBatchRequest(BaseModel):
    """Сравнение КП сразу по нескольким материалам."""
    mk_number: str
    items: List[CompareRequest]


# ---------------------------------------------------------------------------
# Выходные данные
# ---------------------------------------------------------------------------

class ScoreBreakdown(BaseModel):
    """Детализация оценки по критериям для одного поставщика."""
    price:        float    # нормализованная оценка цены [0..1]
    lead_time:    float    # нормализованная оценка срока [0..1]
    verification: float    # 1.0 верифицирован / 0.0 нет
    vat:          float    # 1.0 с НДС / 0.3 без НДС
    supplier_type: float   # manufacturer=1.0 / distributor=0.7 / trader=0.4 / unknown=0.5
    total:        float    # взвешенная сумма


class ScoredQuote(BaseModel):
    """КП с оценкой и рангом."""
    rank: int                      # 1 = лучший
    supplier_name: str
    supplier_type: str
    is_verified: bool
    has_vat: bool
    lead_time_days: int
    unit_price: float
    total_price: float

    scores: ScoreBreakdown
    recommendation: str
    # "recommended" | "alternative" | "not_recommended"


class CompareResult(BaseModel):
    """Результат сравнения по одному материалу."""
    material_name: str
    quantity_required: float
    quotes_count: int

    scored_quotes: List[ScoredQuote]   # отсортированы по score_total desc
    winner: Optional[str] = None       # имя лучшего поставщика
    price_spread_pct: float = 0.0      # разброс цен в %

    weights_used: Dict[str, float]
    summary: str


class CompareBatchResponse(BaseModel):
    """Итоговый ответ агента-Сравнителя."""
    mk_number: str
    results: List[CompareResult]
    overall_summary: str
    warnings: List[str] = []
