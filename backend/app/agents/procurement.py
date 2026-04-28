"""
Агент-Закупщик МК.

Алгоритм:
  1. Своя БД поставщиков (Supabase) — заглушка до подключения БД
  2. Tavily веб-поиск, если своя БД дала < MIN_SUPPLIERS результатов
  3. Claude claude-sonnet-4-6 с tool use:
       - search_web(query)        → Tavily
       - add_supplier(...)        → добавить кандидата в результат
       - generate_rfq(...)        → сформировать RFQ-письмо
  4. Без API ключей — детерминированная заглушка (письмо без поставщиков)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from app.schemas.procurement_schema import (
    ProcurementMaterial,
    ProcurementRequest,
    ProcurementResponse,
    RFQItem,
    RFQLetter,
    SupplierCandidate,
)

logger = logging.getLogger(__name__)

MIN_SUPPLIERS = 2   # если меньше — идём в веб


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _build_search_query(material: ProcurementMaterial, region: str) -> str:
    """Формирует поисковый запрос для Tavily."""
    parts = [f'поставщик "{material.name}"']
    if material.gost:
        parts.append(material.gost)
    parts.append(f"купить {region}")
    parts.append("металлопрокат снабжение")
    return " ".join(parts)


def _rfq_items_text(items: List[RFQItem]) -> str:
    """Форматирует строки материалов для письма."""
    lines = []
    for i, item in enumerate(items, 1):
        line = f"  {i}. {item.material_name} — {item.quantity} {item.unit}"
        if item.gost:
            line += f" ({item.gost})"
        if item.target_price:
            line += f" [ориент. цена: {item.target_price:.2f} руб/{item.unit}]"
        if item.comment:
            line += f" // {item.comment}"
        lines.append(line)
    return "\n".join(lines)


def _build_rfq_letter(
    supplier_name: str,
    supplier_contact: Optional[str],
    items: List[RFQItem],
    company_name: str,
    contact_person: str,
    region: str,
) -> RFQLetter:
    """Генерирует стандартное RFQ-письмо без Claude."""
    today = date.today().strftime("%d.%m.%Y")
    subject = f"Запрос коммерческого предложения на поставку материалов — {today}"
    items_text = _rfq_items_text(items)

    contact_line = f"Контактное лицо: {contact_person}" if contact_person else ""

    body = f"""{supplier_name}

Уважаемые коллеги,

{company_name} рассматривает предложения на поставку следующих материалов \
(регион: {region}):

{items_text}

Просим предоставить коммерческое предложение с указанием:
  — цены за единицу (руб., с НДС и без НДС);
  — срока поставки;
  — условий оплаты;
  — наличия на складе.

Предложения принимаются до {date.today().strftime("%d.%m.%Y")}.

С уважением,
{company_name}
{contact_line}
""".strip()

    return RFQLetter(
        supplier_name=supplier_name,
        supplier_contact=supplier_contact,
        subject=subject,
        body=body,
        items=items,
    )


# ---------------------------------------------------------------------------
# Основной класс
# ---------------------------------------------------------------------------

class ProcurementAgent:
    """
    Агент-Закупщик.
    Ищет поставщиков и генерирует RFQ-письма.
    Использует Claude (tool use) + Tavily если доступны.
    """

    def __init__(
        self,
        anthropic_api_key: Optional[str] = None,
        tavily_api_key: Optional[str] = None,
    ):
        self._anthropic_key = anthropic_api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self._tavily_key    = tavily_api_key    or os.getenv("TAVILY_API_KEY", "")

        self._claude  = None
        self._tavily  = None

        if self._anthropic_key:
            try:
                import anthropic
                self._claude = anthropic.Anthropic(api_key=self._anthropic_key)
                logger.info("ProcurementAgent: Claude API подключён")
            except ImportError:
                logger.warning("ProcurementAgent: anthropic не установлен")

        if self._tavily_key:
            try:
                from tavily import TavilyClient
                self._tavily = TavilyClient(api_key=self._tavily_key)
                logger.info("ProcurementAgent: Tavily API подключён")
            except ImportError:
                logger.warning("ProcurementAgent: tavily-python не установлен")

    # -----------------------------------------------------------------------
    # Публичный метод
    # -----------------------------------------------------------------------

    def procure(self, request: ProcurementRequest) -> ProcurementResponse:
        warnings: List[str] = []

        if not request.materials:
            return ProcurementResponse(
                mk_number=request.mk_number,
                product_name=request.product_name,
                region=request.region,
                materials_to_purchase=[],
                agent_summary="Список материалов к закупке пуст — закупка не требуется.",
                warnings=[],
            )

        # Seed с поставщиками из БД (переданы роутером)
        suppliers: List[SupplierCandidate] = list(request.db_suppliers)
        rfq_letters: List[RFQLetter] = []

        if suppliers:
            logger.info(
                "ProcurementAgent: %d поставщиков из БД (пропускаем их в веб-поиске)",
                len(suppliers),
            )

        if self._claude:
            try:
                suppliers, rfq_letters, ai_warnings = self._run_with_claude(request)
                warnings.extend(ai_warnings)
            except Exception as e:
                logger.error("ProcurementAgent: Claude ошибка: %s", e, exc_info=True)
                warnings.append(f"AI-поиск недоступен: {e}. Сформированы базовые RFQ.")
                rfq_letters = self._fallback_rfq(request)
        else:
            warnings.append(
                "ANTHROPIC_API_KEY не задан — поиск поставщиков недоступен. "
                "Сформированы шаблонные RFQ-письма."
            )
            rfq_letters = self._fallback_rfq(request)

        summary = self._build_summary(request, suppliers, rfq_letters, warnings)

        logger.info(
            "ProcurementAgent: mk=%s, materials=%d, suppliers=%d, rfq=%d, warnings=%d",
            request.mk_number, len(request.materials),
            len(suppliers), len(rfq_letters), len(warnings),
        )

        return ProcurementResponse(
            mk_number=request.mk_number,
            product_name=request.product_name,
            region=request.region,
            materials_to_purchase=request.materials,
            supplier_candidates=suppliers,
            rfq_letters=rfq_letters,
            agent_summary=summary,
            warnings=warnings,
        )

    # -----------------------------------------------------------------------
    # Claude agentic loop
    # -----------------------------------------------------------------------

    def _run_with_claude(
        self, request: ProcurementRequest,
    ) -> Tuple[List[SupplierCandidate], List[RFQLetter], List[str]]:
        """Tool use цикл: Claude ищет поставщиков и формирует RFQ."""
        import anthropic

        warnings: List[str] = []
        suppliers: List[SupplierCandidate] = []
        rfq_letters: List[RFQLetter] = []

        # --- Инструменты ---
        tools = [
            {
                "name": "search_web",
                "description": (
                    "Поиск поставщиков материалов через интернет (Tavily). "
                    "Используй для каждого материала отдельно. "
                    "Возвращает список результатов с названиями компаний и URL."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Поисковый запрос на русском, например: 'поставщик лист г/к Калининград металлопрокат'",
                        },
                        "material_name": {
                            "type": "string",
                            "description": "Название материала (для логирования)",
                        },
                    },
                    "required": ["query", "material_name"],
                },
            },
            {
                "name": "add_supplier",
                "description": (
                    "Добавить найденного поставщика в список кандидатов. "
                    "Вызывай для каждого реального поставщика найденного в поиске."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name":               {"type": "string", "description": "Название компании"},
                        "contact":            {"type": "string", "description": "Email или телефон (если найден)"},
                        "region":             {"type": "string", "description": "Город/регион"},
                        "url":                {"type": "string", "description": "Сайт компании"},
                        "source":             {"type": "string", "enum": ["db", "web"]},
                        "materials_supplied": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Список материалов которые этот поставщик может поставить",
                        },
                        "notes": {"type": "string", "description": "Любые заметки о поставщике"},
                    },
                    "required": ["name", "source", "materials_supplied"],
                },
            },
            {
                "name": "generate_rfq",
                "description": (
                    "Сформировать RFQ-письмо (запрос коммерческого предложения) "
                    "для конкретного поставщика. "
                    "Письмо должно быть профессиональным, на русском языке."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "supplier_name":    {"type": "string"},
                        "supplier_contact": {"type": "string", "description": "Email или телефон"},
                        "subject":          {"type": "string", "description": "Тема письма"},
                        "body":             {
                            "type": "string",
                            "description": (
                                "Полный текст письма на русском языке. "
                                "Включи: приветствие, список материалов с кол-вом и ед., "
                                "просьбу указать цену/срок/условия, подпись."
                            ),
                        },
                        "material_names": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Названия материалов для этого поставщика",
                        },
                    },
                    "required": ["supplier_name", "subject", "body", "material_names"],
                },
            },
        ]

        # Контекст для Claude
        mats_json = json.dumps(
            [m.model_dump() for m in request.materials],
            ensure_ascii=False, indent=2,
        )

        system = (
            f"Ты — агент-закупщик производственного предприятия {request.company_name}.\n\n"
            f"Задача: найти поставщиков для материалов и сформировать RFQ-письма.\n\n"
            f"Регион поставки: {request.region}.\n"
            f"Изделие: {request.product_name} (МК {request.mk_number}).\n\n"
            "Алгоритм:\n"
            "1. Для каждого материала вызови search_web с конкретным запросом.\n"
            "2. Из результатов выбери реальных поставщиков → вызови add_supplier.\n"
            "3. Сгруппируй материалы по поставщикам (один поставщик может поставить несколько).\n"
            "4. Для каждого поставщика вызови generate_rfq с профессиональным письмом.\n\n"
            "Важно:\n"
            "- Добавляй только реальные компании из результатов поиска.\n"
            "- Письма — на русском, деловой стиль.\n"
            "- Если поставщик не найден — всё равно сформируй шаблонное RFQ.\n"
            "- Стремись к минимум 2 поставщикам на материал."
        )

        messages = [
            {
                "role": "user",
                "content": (
                    f"Найди поставщиков и сформируй RFQ для следующих материалов:\n\n"
                    f"```json\n{mats_json}\n```\n\n"
                    f"Контактное лицо от нас: {request.contact_person or 'Менеджер по закупкам'}."
                ),
            }
        ]

        # Agentic loop
        for iteration in range(10):
            response = self._claude.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                system=system,
                tools=tools,
                messages=messages,
            )
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            has_tool_use = False

            for block in response.content:
                if block.type != "tool_use":
                    continue
                has_tool_use = True
                inp = block.input

                # --- search_web ---
                if block.name == "search_web":
                    search_results = self._do_web_search(inp["query"], warnings)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(search_results, ensure_ascii=False),
                    })

                # --- add_supplier ---
                elif block.name == "add_supplier":
                    suppliers.append(SupplierCandidate(
                        name=inp["name"],
                        contact=inp.get("contact"),
                        region=inp.get("region", request.region),
                        url=inp.get("url"),
                        source=inp.get("source", "web"),
                        materials_supplied=inp.get("materials_supplied", []),
                        notes=inp.get("notes"),
                    ))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Поставщик «{inp['name']}» добавлен.",
                    })

                # --- generate_rfq ---
                elif block.name == "generate_rfq":
                    # Формируем RFQItem для материалов поставщика
                    mat_names = set(inp.get("material_names", []))
                    items = [
                        RFQItem(
                            material_name=m.name,
                            unit=m.unit,
                            quantity=m.qty_to_purchase,
                            target_price=m.unit_price_target,
                            gost=m.gost,
                            comment=m.comment,
                        )
                        for m in request.materials
                        if not mat_names or m.name in mat_names
                    ]
                    rfq_letters.append(RFQLetter(
                        supplier_name=inp["supplier_name"],
                        supplier_contact=inp.get("supplier_contact"),
                        subject=inp["subject"],
                        body=inp["body"],
                        items=items,
                    ))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"RFQ для «{inp['supplier_name']}» сформировано.",
                    })

            if response.stop_reason == "end_turn" or not has_tool_use:
                break

            messages.append({"role": "user", "content": tool_results})

        return suppliers, rfq_letters, warnings

    # -----------------------------------------------------------------------
    # Tavily поиск
    # -----------------------------------------------------------------------

    def _do_web_search(self, query: str, warnings: List[str]) -> List[Dict[str, Any]]:
        """Выполняет поиск через Tavily. Возвращает список результатов."""
        if not self._tavily:
            warnings.append("TAVILY_API_KEY не задан — веб-поиск поставщиков недоступен.")
            return []
        try:
            logger.info("ProcurementAgent: Tavily search: %s", query[:80])
            resp = self._tavily.search(
                query=query,
                max_results=5,
                search_depth="basic",
            )
            results = []
            for r in resp.get("results", []):
                results.append({
                    "title":   r.get("title", ""),
                    "url":     r.get("url", ""),
                    "content": r.get("content", "")[:300],
                })
            return results
        except Exception as e:
            logger.warning("ProcurementAgent: Tavily error: %s", e)
            warnings.append(f"Ошибка веб-поиска: {e}")
            return []

    # -----------------------------------------------------------------------
    # Fallback без Claude
    # -----------------------------------------------------------------------

    def _fallback_rfq(self, request: ProcurementRequest) -> List[RFQLetter]:
        """Генерирует шаблонные RFQ без Claude — один общий запрос."""
        items = [
            RFQItem(
                material_name=m.name,
                unit=m.unit,
                quantity=m.qty_to_purchase,
                target_price=m.unit_price_target,
                gost=m.gost,
                comment=m.comment,
            )
            for m in request.materials
        ]
        letter = _build_rfq_letter(
            supplier_name="[Наименование поставщика]",
            supplier_contact=None,
            items=items,
            company_name=request.company_name,
            contact_person=request.contact_person,
            region=request.region,
        )
        return [letter]

    # -----------------------------------------------------------------------
    # Резюме
    # -----------------------------------------------------------------------

    def _build_summary(
        self,
        request: ProcurementRequest,
        suppliers: List[SupplierCandidate],
        rfq_letters: List[RFQLetter],
        warnings: List[str],
    ) -> str:
        parts = [
            f"Закупка по МК {request.mk_number} — {request.product_name}.",
            f"Материалов к закупке: {len(request.materials)}.",
        ]
        if suppliers:
            parts.append(f"Найдено поставщиков: {len(suppliers)}.")
        else:
            parts.append("Поставщики не найдены (нет ключей API или нет результатов).")
        if rfq_letters:
            parts.append(f"Сформировано RFQ-писем: {len(rfq_letters)}.")
        if warnings:
            parts.append(f"Предупреждений: {len(warnings)}.")
        return " ".join(parts)
