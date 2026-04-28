"""
Схемы для агента-Закупщика.

Поток:
  1. Принимает список материалов к закупке (из CalculatorResponse)
  2. Ищет поставщиков: сначала своя БД, затем Tavily (веб-поиск)
  3. Генерирует RFQ-письма для каждого поставщика
  4. Возвращает ProcurementResponse с кандидатами и готовыми письмами
"""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Входные данные
# ---------------------------------------------------------------------------

class ProcurementMaterial(BaseModel):
    """Материал, который нужно закупить."""
    name: str
    unit: str
    qty_to_purchase: float
    unit_price_target: Optional[float] = None  # ориентировочная цена (из истории)
    gost: Optional[str] = None                 # ГОСТ/ТУ (для поиска)
    comment: Optional[str] = None


class ProcurementRequest(BaseModel):
    """Запрос на поиск поставщиков и формирование RFQ."""
    mk_number: str
    article: str
    product_name: str

    materials: List[ProcurementMaterial]       # только те, у которых qty_to_purchase > 0

    region: str = "Калининград"                # регион поиска поставщиков
    company_name: str = 'ООО "Петробалт Сервис"'
    contact_person: str = ""                   # подписант в письмах


# ---------------------------------------------------------------------------
# Выходные данные
# ---------------------------------------------------------------------------

class SupplierCandidate(BaseModel):
    """Найденный кандидат-поставщик."""
    name: str
    contact: Optional[str] = None             # email / телефон
    region: Optional[str] = None
    url: Optional[str] = None
    source: str = "web"                       # "db" | "web"
    materials_supplied: List[str] = []        # какие материалы может поставить
    notes: Optional[str] = None


class RFQItem(BaseModel):
    """Строка в запросе коммерческого предложения."""
    material_name: str
    unit: str
    quantity: float
    target_price: Optional[float] = None
    gost: Optional[str] = None
    comment: Optional[str] = None


class RFQLetter(BaseModel):
    """Готовое RFQ-письмо для одного поставщика."""
    supplier_name: str
    supplier_contact: Optional[str] = None
    subject: str
    body: str                                 # полный текст на русском
    items: List[RFQItem] = []


class ProcurementResponse(BaseModel):
    """Результат работы агента-Закупщика."""
    mk_number: str
    product_name: str
    region: str

    materials_to_purchase: List[ProcurementMaterial]
    supplier_candidates: List[SupplierCandidate] = []
    rfq_letters: List[RFQLetter] = []

    agent_summary: str = ""
    warnings: List[str] = []
