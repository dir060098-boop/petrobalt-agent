from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Каждое поле несёт значение + статус агента
# ---------------------------------------------------------------------------

class FieldValue(BaseModel):
    value: Any = None
    status: str = "missing"
    # missing / extracted / calculated / manual / confirmed / rejected / not_applicable
    source: str = "mk"

    @field_validator("status")
    @classmethod
    def check_status(cls, v: str) -> str:
        allowed = {
            "missing", "extracted", "calculated",
            "manual", "confirmed", "rejected", "not_applicable",
        }
        if v not in allowed:
            raise ValueError(f"status must be one of {allowed}")
        return v

    @classmethod
    def extracted(cls, value: Any, source: str = "mk") -> "FieldValue":
        if value is None or (isinstance(value, str) and not value.strip()):
            return cls(value=None, status="missing", source=source)
        return cls(value=value, status="extracted", source=source)

    @classmethod
    def missing(cls, source: str = "mk") -> "FieldValue":
        return cls(value=None, status="missing", source=source)


# ---------------------------------------------------------------------------
# Плановые материалы (таблица "Материалы, планируемые к использованию")
# ---------------------------------------------------------------------------

class PlannedMaterial(BaseModel):
    position: Optional[int] = None
    name: FieldValue
    unit: FieldValue
    qty_issued: FieldValue        # вес материалов, отпущенных со склада
    qty_per_unit: FieldValue      # кол-во на 1 ед. изделия
    qty_total: FieldValue         # кол-во итого


# ---------------------------------------------------------------------------
# Вспомогательные / доп. материалы
# ---------------------------------------------------------------------------

class AuxMaterial(BaseModel):
    position: Optional[int] = None
    name: FieldValue
    unit: FieldValue
    qty_per_unit: FieldValue
    qty_total: FieldValue


# ---------------------------------------------------------------------------
# Технологические операции
# ---------------------------------------------------------------------------

class Operation(BaseModel):
    sequence: Optional[int] = None
    operation_name: FieldValue
    instruction_no: FieldValue
    department: FieldValue
    tech_description: FieldValue
    comments: FieldValue


# ---------------------------------------------------------------------------
# Инспекция
# ---------------------------------------------------------------------------

class InspectionItem(BaseModel):
    sequence: Optional[int] = None
    operation_name: FieldValue
    instruction_no: FieldValue
    department: FieldValue
    required_value: FieldValue
    actual_value: FieldValue
    inspected_by: FieldValue


# ---------------------------------------------------------------------------
# Фактические материалы (страница 2)
# ---------------------------------------------------------------------------

class ActualMaterial(BaseModel):
    position: Optional[int] = None
    name: FieldValue
    unit: FieldValue
    qty_per_unit: FieldValue
    qty_total: FieldValue
    qty_remainder: FieldValue
    qty_returned: FieldValue      # возврат на склад
    qty_recycled: FieldValue      # утилизация


# ---------------------------------------------------------------------------
# Упаковка / маркировка (страница 3)
# ---------------------------------------------------------------------------

class PackagingMaterial(BaseModel):
    position: Optional[int] = None
    description: FieldValue
    material_type: FieldValue     # "в составе продукции" / "упаковочный материал"
    unit: FieldValue
    qty: FieldValue


# ---------------------------------------------------------------------------
# Итоговый результат парсинга МК
# ---------------------------------------------------------------------------

class MKParseResult(BaseModel):
    # Заголовок
    mk_number: FieldValue
    article: FieldValue
    product_name: FieldValue
    quantity: FieldValue
    quantity_unit: FieldValue
    date_start: FieldValue
    date_end: FieldValue
    created_by: FieldValue
    verified_by: FieldValue

    # Тело
    planned_materials: list[PlannedMaterial] = []
    operations: list[Operation] = []
    inspection: list[InspectionItem] = []
    actual_materials: list[ActualMaterial] = []
    aux_materials: list[AuxMaterial] = []

    # Масса готовой продукции
    mass_before_trim_kg: FieldValue
    mass_after_trim_kg: FieldValue

    # Упаковка
    packaging_materials: list[PackagingMaterial] = []

    # Служебные поля парсера
    parse_errors: list[str] = []
    missing_critical_fields: list[str] = []
    confidence: float = 0.0           # 0.0 – 1.0
    total_pages: int = 0
    raw_text: str = ""

    def compute_confidence(self) -> None:
        """Вычисляет confidence как долю заполненных критичных полей."""
        critical = [
            self.mk_number, self.article, self.product_name,
            self.quantity, self.date_start,
        ]
        filled = sum(1 for f in critical if f.status != "missing")
        self.confidence = round(filled / len(critical), 2)

        self.missing_critical_fields = [
            name for name, field in {
                "mk_number": self.mk_number,
                "article": self.article,
                "product_name": self.product_name,
                "quantity": self.quantity,
                "date_start": self.date_start,
            }.items()
            if field.status == "missing"
        ]
