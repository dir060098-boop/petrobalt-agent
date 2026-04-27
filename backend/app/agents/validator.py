"""
Агент-Проверяющий МК.

Работает в два этапа:
  1. Детерминированная проверка:
       - критичные поля присутствуют?
       - форматы корректны?
       - применяем подтверждения пользователя

  2. Семантическая проверка (Claude claude-sonnet-4-6):
       - соответствие артикула и наименования продукции
       - разумность значений (количество, даты)
       - итоговое резюме на русском языке

Если ANTHROPIC_API_KEY не задан — второй этап пропускается,
агент работает только детерминированно.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from app.schemas.validator_schema import (
    FieldConfirmation,
    IssueSeverity,
    ValidatedField,
    ValidationIssue,
    ValidatorRequest,
    ValidatorResponse,
)

logger = logging.getLogger(__name__)

# Критичные поля — их отсутствие блокирует расчёт
CRITICAL_FIELDS = ["mk_number", "article", "product_name", "quantity", "date_start"]

# Все поля заголовка МК
HEADER_FIELDS = [
    "mk_number", "article", "product_name", "quantity",
    "quantity_unit", "date_start", "date_end", "created_by", "verified_by",
]


# ---------------------------------------------------------------------------
# Детерминированные валидаторы полей
# ---------------------------------------------------------------------------

def _validate_mk_number(value: Any) -> Optional[str]:
    """Формат: NN-NN.NN или NN-NN.NNNN (например, 01-04.26)."""
    if not value:
        return None
    if not re.match(r"^\d{2}-\d{2}\.\d{2,4}$", str(value)):
        return f"Неожиданный формат номера МК: «{value}». Ожидается NN-NN.YY"
    return None


def _validate_quantity(value: Any) -> Optional[str]:
    try:
        qty = float(value)
    except (TypeError, ValueError):
        return f"Количество «{value}» не является числом"
    if qty <= 0:
        return "Количество должно быть больше нуля"
    if qty > 100_000:
        return f"Количество {qty} выглядит слишком большим — проверьте значение"
    return None


def _validate_date(value: Any, field_label: str) -> Optional[str]:
    """Проверяем что дата в формате D.M.YY, DD.MM.YY или DD.MM.YYYY."""
    if not value:
        return None
    if not re.match(r"^\d{1,2}\.\d{1,2}\.\d{2,4}$", str(value)):
        return f"{field_label}: не удалось распознать дату «{value}»"
    return None


# ---------------------------------------------------------------------------
# Основной класс агента
# ---------------------------------------------------------------------------

class ValidatorAgent:
    """
    Агент-Проверяющий МК.
    Использует Claude API для семантической валидации (если есть API ключ).
    """

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self._client = None

        if self._api_key:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self._api_key)
                logger.info("ValidatorAgent: Claude API подключён (claude-sonnet-4-6)")
            except ImportError:
                logger.warning("ValidatorAgent: anthropic не установлен, работаем без AI")
        else:
            logger.info("ValidatorAgent: ANTHROPIC_API_KEY не задан, только детерминированная проверка")

    # -----------------------------------------------------------------------
    # Публичный метод
    # -----------------------------------------------------------------------

    def validate(self, request: ValidatorRequest) -> ValidatorResponse:
        """Валидирует данные МК и возвращает результат."""

        # 1. Строим словарь полей из запроса
        raw_fields = self._extract_raw_fields(request)

        # 2. Применяем подтверждения пользователя
        fields, applied = self._apply_confirmations(raw_fields, request.field_statuses, request.confirmations)

        # 3. Детерминированные проверки
        issues = self._run_deterministic_checks(fields, request)

        # 4. AI-проверка (если доступна)
        ai_summary = None
        if self._client:
            try:
                ai_issues, ai_summary = self._run_ai_checks(fields, request, issues)
                issues.extend(ai_issues)
            except Exception as e:
                logger.warning("ValidatorAgent: AI-проверка не удалась: %s", e)
                issues.append(ValidationIssue(
                    field="general",
                    severity=IssueSeverity.warning,
                    message=f"AI-проверка недоступна: {e}. Результат основан только на детерминированной проверке.",
                ))

        # 5. Определяем итоговый статус
        missing_critical = [
            f for f in CRITICAL_FIELDS
            if fields.get(f, ValidatedField()).status == "missing"
        ]
        critical_issues = [i for i in issues if i.severity == IssueSeverity.critical]
        ready = len(missing_critical) == 0 and len(critical_issues) == 0

        if ready:
            status = "ready"
            blocked_reason = None
            summary = ai_summary or (
                f"МК проверена успешно. Все критичные поля заполнены. "
                f"Плановых материалов: {request.planned_materials_count}, "
                f"фактических: {request.actual_materials_count}."
            )
        else:
            status = "needs_input"
            parts = []
            if missing_critical:
                parts.append(f"отсутствуют поля: {', '.join(missing_critical)}")
            if critical_issues:
                parts.append("; ".join(i.message for i in critical_issues))
            blocked_reason = "МК не может быть передана в расчёт — " + "; ".join(parts)
            summary = ai_summary or (
                f"МК требует доработки: {blocked_reason}. "
                f"Заполните недостающие поля и повторите проверку."
            )

        logger.info(
            "ValidatorAgent: status=%s, missing=%s, issues=%d (critical=%d)",
            status, missing_critical, len(issues), len(critical_issues),
        )

        return ValidatorResponse(
            ready_for_calculation=ready,
            status=status,
            validated_fields=fields,
            issues=issues,
            agent_summary=summary,
            blocked_reason=blocked_reason,
            missing_critical=missing_critical,
        )

    # -----------------------------------------------------------------------
    # Вспомогательные методы
    # -----------------------------------------------------------------------

    def _extract_raw_fields(self, req: ValidatorRequest) -> Dict[str, ValidatedField]:
        """Строит начальный словарь полей из данных запроса."""
        data = {
            "mk_number":    req.mk_number,
            "article":      req.article,
            "product_name": req.product_name,
            "quantity":     req.quantity,
            "quantity_unit": req.quantity_unit,
            "date_start":   req.date_start,
            "date_end":     req.date_end,
            "created_by":   req.created_by,
            "verified_by":  req.verified_by,
        }
        fields: Dict[str, ValidatedField] = {}
        for name, value in data.items():
            status = req.field_statuses.get(name, "missing" if value is None else "extracted")
            fields[name] = ValidatedField(value=value, status=status, source="mk")
        return fields

    def _apply_confirmations(
        self,
        fields: Dict[str, ValidatedField],
        original_statuses: Dict[str, str],
        confirmations: List[FieldConfirmation],
    ) -> Tuple[Dict[str, ValidatedField], List[str]]:
        """Применяет подтверждения пользователя к полям."""
        applied = []
        for conf in confirmations:
            name = conf.field_name
            orig_status = original_statuses.get(name, "missing")
            # confirmed = было extracted и пользователь подтвердил
            # manual    = было missing и пользователь ввёл
            new_status = "confirmed" if orig_status == "extracted" else "manual"
            fields[name] = ValidatedField(value=conf.value, status=new_status, source="user")
            applied.append(name)
            logger.debug("ValidatorAgent: field %s → %s (value=%s)", name, new_status, conf.value)
        return fields, applied

    def _run_deterministic_checks(
        self,
        fields: Dict[str, ValidatedField],
        req: ValidatorRequest,
    ) -> List[ValidationIssue]:
        """Детерминированные проверки форматов и обязательных полей."""
        issues: List[ValidationIssue] = []

        # --- Критичные обязательные поля ---
        critical_labels = {
            "mk_number":    "Номер МК",
            "article":      "Артикул",
            "product_name": "Наименование продукции",
            "quantity":     "Количество",
            "date_start":   "Дата составления",
        }
        for fname, label in critical_labels.items():
            fval = fields.get(fname, ValidatedField())
            if fval.status == "missing" or fval.value is None:
                issues.append(ValidationIssue(
                    field=fname,
                    severity=IssueSeverity.critical,
                    message=f"Критичное поле «{label}» отсутствует в МК.",
                    suggestion=f"Введите {label} вручную",
                ))

        # --- Форматные проверки ---
        mk_err = _validate_mk_number(fields.get("mk_number", ValidatedField()).value)
        if mk_err:
            issues.append(ValidationIssue(field="mk_number", severity=IssueSeverity.warning, message=mk_err))

        qty_err = _validate_quantity(fields.get("quantity", ValidatedField()).value)
        if qty_err:
            issues.append(ValidationIssue(field="quantity", severity=IssueSeverity.critical, message=qty_err))

        for fname, label in [("date_start", "Дата составления"), ("date_end", "Дата окончания")]:
            d_err = _validate_date(fields.get(fname, ValidatedField()).value, label)
            if d_err:
                issues.append(ValidationIssue(field=fname, severity=IssueSeverity.warning, message=d_err))

        # --- Предупреждения о материалах ---
        if req.planned_materials_count == 0:
            issues.append(ValidationIssue(
                field="planned_materials",
                severity=IssueSeverity.warning,
                message="Таблица плановых материалов не найдена или пуста.",
                suggestion="Проверьте, что МК содержит страницу с плановыми материалами",
            ))

        # --- Ошибки парсера ---
        for err in req.parse_errors:
            issues.append(ValidationIssue(
                field="general",
                severity=IssueSeverity.warning,
                message=f"Ошибка при чтении МК: {err}",
            ))

        return issues

    # -----------------------------------------------------------------------
    # AI-проверка через Claude
    # -----------------------------------------------------------------------

    def _run_ai_checks(
        self,
        fields: Dict[str, ValidatedField],
        req: ValidatorRequest,
        existing_issues: List[ValidationIssue],
    ) -> Tuple[List[ValidationIssue], str]:
        """
        Семантическая проверка через Claude claude-sonnet-4-6.
        Возвращает (дополнительные_проблемы, резюме).
        """
        import anthropic

        # Подготавливаем контекст для Claude
        fields_summary = {
            name: {"value": f.value, "status": f.status}
            for name, f in fields.items()
        }
        existing_issues_summary = [
            {"field": i.field, "severity": i.severity, "message": i.message}
            for i in existing_issues
        ]

        context = json.dumps({
            "mk_fields": fields_summary,
            "planned_materials_count": req.planned_materials_count,
            "actual_materials_count": req.actual_materials_count,
            "operations_count": req.operations_count,
            "parser_confidence": req.confidence,
            "existing_issues": existing_issues_summary,
        }, ensure_ascii=False, indent=2)

        # Инструменты для Claude
        tools = [
            {
                "name": "add_issue",
                "description": (
                    "Добавить проблему, найденную в данных МК. "
                    "Используй только если обнаружена реальная проблема — не дублируй уже найденные."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "field": {
                            "type": "string",
                            "description": "Имя поля или 'general' для общих проблем",
                        },
                        "severity": {
                            "type": "string",
                            "enum": ["critical", "warning", "info"],
                            "description": "critical = блокирует расчёт, warning = требует внимания",
                        },
                        "message": {
                            "type": "string",
                            "description": "Сообщение для пользователя на русском языке",
                        },
                        "suggestion": {
                            "type": "string",
                            "description": "Подсказка что сделать (опционально)",
                        },
                    },
                    "required": ["field", "severity", "message"],
                },
            },
            {
                "name": "set_summary",
                "description": "Установить итоговое резюме проверки МК для пользователя.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": (
                                "2-4 предложения на русском: что проверено, "
                                "что в порядке, что требует внимания."
                            ),
                        },
                    },
                    "required": ["summary"],
                },
            },
        ]

        system_prompt = (
            "Ты — агент-проверяющий Маршрутных Карт (МК) производственного предприятия "
            "ООО «Петробалт Сервис» (биметаллические пластины, буровое оборудование).\n\n"
            "Твоя задача: провести семантическую проверку данных МК и:\n"
            "1. Добавить проблемы через инструмент add_issue — ТОЛЬКО если обнаружено "
            "что-то реально подозрительное (не дублируй уже найденные ошибки).\n"
            "2. Вызвать set_summary с кратким резюме для пользователя.\n\n"
            "Проверяй:\n"
            "- Соответствие артикула формату (должен содержать цифры и точки)\n"
            "- Наименование продукции соответствует типичным изделиям предприятия\n"
            "- Количество изделий разумно (обычно 1–1000 штук)\n"
            "- Если confidence парсера < 0.6 — предупреди пользователя\n"
            "- Если фактических материалов нет, а плановые есть — предупреди\n\n"
            "НЕ добавляй проблемы которые уже есть в existing_issues.\n"
            "Отвечай только на русском языке."
        )

        messages = [
            {
                "role": "user",
                "content": (
                    f"Проверь данные маршрутной карты:\n\n```json\n{context}\n```\n\n"
                    "Используй инструменты add_issue и set_summary."
                ),
            }
        ]

        ai_issues: List[ValidationIssue] = []
        ai_summary = "Проверка завершена."

        # Цикл tool use (agentic loop)
        max_iterations = 5
        for iteration in range(max_iterations):
            response = self._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=system_prompt,
                tools=tools,
                messages=messages,
            )

            # Добавляем ответ агента в историю
            messages.append({"role": "assistant", "content": response.content})

            # Обрабатываем tool calls
            tool_results = []
            has_tool_use = False

            for block in response.content:
                if block.type != "tool_use":
                    continue
                has_tool_use = True
                tool_input = block.input

                if block.name == "add_issue":
                    ai_issues.append(ValidationIssue(
                        field=tool_input.get("field", "general"),
                        severity=IssueSeverity(tool_input.get("severity", "info")),
                        message=tool_input.get("message", ""),
                        suggestion=tool_input.get("suggestion"),
                    ))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "Проблема добавлена.",
                    })

                elif block.name == "set_summary":
                    ai_summary = tool_input.get("summary", ai_summary)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "Резюме сохранено.",
                    })

            # Если Claude закончил — выходим
            if response.stop_reason == "end_turn" or not has_tool_use:
                break

            # Передаём результаты инструментов обратно
            messages.append({"role": "user", "content": tool_results})

        logger.info(
            "ValidatorAgent AI: %d дополнительных проблем, summary=%s",
            len(ai_issues), ai_summary[:60],
        )
        return ai_issues, ai_summary
