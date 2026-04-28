"""
Схемы для агента-Проверяющего МК.

Поток:
  1. Клиент отправляет результат парсинга (MKParseResponse) + подтверждения пользователя
  2. Агент возвращает ValidatorResponse:
       - ready_for_calculation = True  → можно передавать Агенту-Расчётчику
       - ready_for_calculation = False → нужен ввод пользователя (issues с severity=critical)
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class IssueSeverity(str, Enum):
    critical = "critical"   # блокирует расчёт
    warning  = "warning"    # не блокирует, но требует внимания
    info     = "info"       # информационное


class ValidationIssue(BaseModel):
    field: str                  # имя поля или "general"
    severity: IssueSeverity
    message: str                # сообщение для пользователя (на русском)
    suggestion: Optional[str] = None  # подсказка что ввести


class FieldConfirmation(BaseModel):
    """Подтверждение / ручной ввод одного поля пользователем."""
    field_name: str
    value: Any
    # статус становится "confirmed" если поле было extracted, "manual" если было missing


class ValidatedField(BaseModel):
    """Поле после валидации — value + итоговый статус."""
    value: Any = None
    status: str = "missing"     # extracted / confirmed / manual / missing / rejected
    source: str = "mk"


class ValidatorRequest(BaseModel):
    """Запрос на валидацию МК."""

    # Поля заголовка из результата парсинга
    mk_number:    Optional[str] = None
    article:      Optional[str] = None
    product_name: Optional[str] = None
    quantity:     Optional[float] = None
    quantity_unit: Optional[str] = None
    date_start:   Optional[str] = None
    date_end:     Optional[str] = None
    created_by:   Optional[str] = None
    verified_by:  Optional[str] = None

    # Статусы из парсера (extracted / missing / ...)
    field_statuses: Dict[str, str] = {}

    # Количество плановых и фактических материалов
    planned_materials_count: int = 0
    actual_materials_count:  int = 0
    operations_count:        int = 0

    # Ошибки парсера
    parse_errors: List[str] = []
    confidence: float = 0.0

    # Подтверждения / правки от пользователя (опционально)
    confirmations: List[FieldConfirmation] = []


class ValidatorResponse(BaseModel):
    """Результат валидации МК агентом-Проверяющим."""

    ready_for_calculation: bool
    status: str  # "ready" | "needs_input" | "rejected"

    # Итоговые поля после применения подтверждений
    validated_fields: Dict[str, ValidatedField]

    # Список проблем
    issues: List[ValidationIssue]

    # Резюме агента (текст на русском)
    agent_summary: str

    # Если не ready — причина блокировки
    blocked_reason: Optional[str] = None

    # Критичные поля, которых всё ещё не хватает
    missing_critical: List[str] = []
