"""
FastAPI роутер для работы с Маршрутными Картами (МК).

Endpoints:
  POST /api/mk/parse      — загрузить PDF, получить распарсенный MKParseResult
  POST /api/mk/validate   — валидировать данные МК агентом-Проверяющим
  POST /api/mk/calculate  — рассчитать BOM и себестоимость агентом-Расчётчиком
  POST /api/mk/procure    — найти поставщиков и сформировать RFQ агентом-Закупщиком
  POST /api/mk/compare    — сравнить КП от поставщиков агентом-Сравнителем
  GET  /api/mk/fields     — справочник статусов полей
"""

from __future__ import annotations

import tempfile
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.parsers.mk_parser import MKParser
from app.schemas.mk_schema import FieldValue, MKParseResult
from app.schemas.validator_schema import ValidatorRequest, ValidatorResponse
from app.schemas.calculator_schema import CalculatorRequest, CalculatorResponse
from app.schemas.procurement_schema import ProcurementRequest, ProcurementResponse
from app.schemas.comparator_schema import CompareBatchRequest, CompareBatchResponse
from app.agents.validator import ValidatorAgent
from app.agents.calculator import CalculatorAgent
from app.agents.procurement import ProcurementAgent
from app.agents.comparator import ComparatorAgent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/mk", tags=["МК — Маршрутные карты"])


# ---------------------------------------------------------------------------
# Response-модели (упрощённые для JSON-сериализации)
# ---------------------------------------------------------------------------

class FieldOut(BaseModel):
    value: Any = None
    status: str = "missing"
    source: str = "mk"

    @classmethod
    def from_field(cls, f: FieldValue) -> "FieldOut":
        return cls(value=f.value, status=f.status, source=f.source)


class MaterialOut(BaseModel):
    position: Optional[int] = None
    name: FieldOut
    unit: FieldOut
    qty_issued: Optional[FieldOut] = None
    qty_per_unit: FieldOut
    qty_total: FieldOut


class ActualMaterialOut(BaseModel):
    position: Optional[int] = None
    name: FieldOut
    unit: FieldOut
    qty_per_unit: FieldOut
    qty_total: FieldOut
    qty_remainder: FieldOut
    qty_returned: FieldOut
    qty_recycled: FieldOut


class OperationOut(BaseModel):
    sequence: Optional[int] = None
    operation_name: FieldOut
    instruction_no: FieldOut
    department: FieldOut
    tech_description: FieldOut
    comments: FieldOut


class MKParseResponse(BaseModel):
    """Ответ эндпоинта парсинга МК."""

    # Служебные поля
    success: bool
    confidence: float
    total_pages: int
    parse_errors: List[str]
    missing_critical_fields: List[str]

    # Заголовок МК
    mk_number: FieldOut
    article: FieldOut
    product_name: FieldOut
    quantity: FieldOut
    quantity_unit: FieldOut
    date_start: FieldOut
    date_end: FieldOut
    created_by: FieldOut
    verified_by: FieldOut

    # Материалы и операции
    planned_materials: List[MaterialOut]
    actual_materials: List[ActualMaterialOut]
    operations: List[OperationOut]

    # Масса
    mass_before_trim_kg: FieldOut
    mass_after_trim_kg: FieldOut


def _build_response(result: MKParseResult) -> MKParseResponse:
    """Конвертирует MKParseResult в MKParseResponse."""

    planned_out = []
    for m in result.planned_materials:
        planned_out.append(MaterialOut(
            position=m.position,
            name=FieldOut.from_field(m.name),
            unit=FieldOut.from_field(m.unit),
            qty_issued=FieldOut.from_field(m.qty_issued),
            qty_per_unit=FieldOut.from_field(m.qty_per_unit),
            qty_total=FieldOut.from_field(m.qty_total),
        ))

    actual_out = []
    for m in result.actual_materials:
        actual_out.append(ActualMaterialOut(
            position=m.position,
            name=FieldOut.from_field(m.name),
            unit=FieldOut.from_field(m.unit),
            qty_per_unit=FieldOut.from_field(m.qty_per_unit),
            qty_total=FieldOut.from_field(m.qty_total),
            qty_remainder=FieldOut.from_field(m.qty_remainder),
            qty_returned=FieldOut.from_field(m.qty_returned),
            qty_recycled=FieldOut.from_field(m.qty_recycled),
        ))

    ops_out = []
    for op in result.operations:
        ops_out.append(OperationOut(
            sequence=op.sequence,
            operation_name=FieldOut.from_field(op.operation_name),
            instruction_no=FieldOut.from_field(op.instruction_no),
            department=FieldOut.from_field(op.department),
            tech_description=FieldOut.from_field(op.tech_description),
            comments=FieldOut.from_field(op.comments),
        ))

    return MKParseResponse(
        success=result.confidence > 0,
        confidence=result.confidence,
        total_pages=result.total_pages,
        parse_errors=result.parse_errors,
        missing_critical_fields=result.missing_critical_fields,

        mk_number=FieldOut.from_field(result.mk_number),
        article=FieldOut.from_field(result.article),
        product_name=FieldOut.from_field(result.product_name),
        quantity=FieldOut.from_field(result.quantity),
        quantity_unit=FieldOut.from_field(result.quantity_unit),
        date_start=FieldOut.from_field(result.date_start),
        date_end=FieldOut.from_field(result.date_end),
        created_by=FieldOut.from_field(result.created_by),
        verified_by=FieldOut.from_field(result.verified_by),

        planned_materials=planned_out,
        actual_materials=actual_out,
        operations=ops_out,

        mass_before_trim_kg=FieldOut.from_field(result.mass_before_trim_kg),
        mass_after_trim_kg=FieldOut.from_field(result.mass_after_trim_kg),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

_parser      = MKParser()
_validator   = ValidatorAgent()    # подхватит ANTHROPIC_API_KEY из env
_calculator  = CalculatorAgent()   # детерминированный, без API
_procurement = ProcurementAgent()  # подхватит ANTHROPIC_API_KEY + TAVILY_API_KEY
_comparator  = ComparatorAgent()   # детерминированный, без API


@router.post(
    "/parse",
    response_model=MKParseResponse,
    status_code=status.HTTP_200_OK,
    summary="Загрузить PDF с МК и получить распарсенные данные",
    description=(
        "Принимает PDF-файл Маршрутной Карты (МК). "
        "Возвращает все извлечённые поля с их статусами (extracted / missing). "
        "Файл временно сохраняется и автоматически удаляется после парсинга."
    ),
)
async def parse_mk(
    file: UploadFile = File(..., description="PDF-файл МК"),
) -> MKParseResponse:
    # Проверяем тип файла
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Ожидается PDF-файл (.pdf)",
        )

    # Читаем содержимое
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Файл пустой",
        )
    if len(content) > 50 * 1024 * 1024:  # 50 MB
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Файл слишком большой (максимум 50 МБ)",
        )

    # Сохраняем во временный файл и парсим
    suffix = Path(file.filename).suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        logger.info("MK parse request: file=%s, size=%d bytes", file.filename, len(content))
        result = _parser.parse(tmp_path)
        response = _build_response(result)

        logger.info(
            "MK parse done: mk=%s, confidence=%.2f, planned=%d, actual=%d, errors=%d",
            result.mk_number.value,
            result.confidence,
            len(result.planned_materials),
            len(result.actual_materials),
            len(result.parse_errors),
        )
        return response

    except Exception as e:
        logger.error("MK parse failed for %s: %s", file.filename, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка парсинга МК: {e}",
        )
    finally:
        tmp_path.unlink(missing_ok=True)


@router.post(
    "/validate",
    response_model=ValidatorResponse,
    status_code=status.HTTP_200_OK,
    summary="Валидировать данные МК агентом-Проверяющим",
    description=(
        "Принимает данные МК (результат /parse) и опциональные подтверждения пользователя. "
        "Агент-Проверяющий проверяет полноту и корректность данных. "
        "Если все критичные поля заполнены → ready_for_calculation=true. "
        "Иначе возвращает список проблем с указанием что нужно заполнить вручную."
    ),
)
async def validate_mk(request: ValidatorRequest) -> ValidatorResponse:
    try:
        logger.info(
            "MK validate request: mk=%s, confidence=%.2f, confirmations=%d",
            request.mk_number, request.confidence, len(request.confirmations),
        )
        result = _validator.validate(request)
        logger.info(
            "MK validate done: status=%s, ready=%s, issues=%d",
            result.status, result.ready_for_calculation, len(result.issues),
        )
        return result
    except Exception as e:
        logger.error("MK validate failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка валидации МК: {e}",
        )


@router.post(
    "/calculate",
    response_model=CalculatorResponse,
    status_code=status.HTTP_200_OK,
    summary="Рассчитать BOM и себестоимость",
    description=(
        "Принимает подтверждённые данные МК и список материалов. "
        "Рассчитывает qty_required с коэффициентами отхода, себестоимость, "
        "потребность в закупке (qty_to_purchase = qty_required - qty_in_stock). "
        "Snapshot цен фиксируется в поле snapshot_at."
    ),
)
async def calculate_mk(request: CalculatorRequest) -> CalculatorResponse:
    try:
        logger.info(
            "MK calculate request: mk=%s, qty=%s, materials=%d",
            request.mk_number, request.quantity, len(request.materials),
        )
        result = _calculator.calculate(request)
        logger.info(
            "MK calculate done: total_cost=%s, needs_purchase=%s, warnings=%d",
            result.total_cost, result.needs_purchase, len(result.warnings),
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        logger.error("MK calculate failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка расчёта МК: {e}",
        )


@router.post(
    "/procure",
    response_model=ProcurementResponse,
    status_code=status.HTTP_200_OK,
    summary="Найти поставщиков и сформировать RFQ-письма",
    description=(
        "Принимает список материалов к закупке (qty_to_purchase > 0). "
        "Агент-Закупщик ищет поставщиков в своей БД и через Tavily, "
        "затем с помощью Claude формирует RFQ-письма на русском языке. "
        "Без API-ключей возвращает шаблонные письма."
    ),
)
async def procure_mk(request: ProcurementRequest) -> ProcurementResponse:
    try:
        logger.info(
            "MK procure request: mk=%s, materials=%d, region=%s",
            request.mk_number, len(request.materials), request.region,
        )
        result = _procurement.procure(request)
        logger.info(
            "MK procure done: suppliers=%d, rfq=%d, warnings=%d",
            len(result.supplier_candidates), len(result.rfq_letters), len(result.warnings),
        )
        return result
    except Exception as e:
        logger.error("MK procure failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка поиска поставщиков: {e}",
        )


@router.post(
    "/compare",
    response_model=CompareBatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Сравнить КП от поставщиков (weighted scoring)",
    description=(
        "Принимает список КП по одному или нескольким материалам. "
        "Агент-Сравнитель присваивает взвешенный score каждому поставщику: "
        "цена 40% + срок 25% + верификация 15% + НДС 10% + тип 10%. "
        "Возвращает ранжированный список с рекомендацией."
    ),
)
async def compare_quotes(request: CompareBatchRequest) -> CompareBatchResponse:
    try:
        logger.info(
            "MK compare request: mk=%s, materials=%d",
            request.mk_number, len(request.items),
        )
        result = _comparator.compare_batch(request)
        logger.info(
            "MK compare done: results=%d, warnings=%d",
            len(result.results), len(result.warnings),
        )
        return result
    except Exception as e:
        logger.error("MK compare failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка сравнения КП: {e}",
        )


@router.get(
    "/fields",
    summary="Список полей МК и их статусов",
    description="Возвращает описание всех возможных статусов полей для фронтенда.",
)
async def get_field_statuses() -> Dict[str, Any]:
    return {
        "statuses": {
            "extracted": "Извлечено из МК автоматически",
            "missing":   "Отсутствует в МК — требует ручного ввода",
            "calculated": "Рассчитано агентом",
            "manual":    "Введено вручную пользователем",
            "confirmed": "Подтверждено пользователем",
            "rejected":  "Отклонено пользователем",
            "not_applicable": "Не применимо для данного МК",
        },
        "critical_fields": [
            "mk_number", "article", "product_name", "quantity", "date_start",
        ],
    }
