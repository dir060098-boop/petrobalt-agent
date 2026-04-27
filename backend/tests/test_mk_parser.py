"""
Тест парсера МК на реальном файле.
Запуск: python -m pytest backend/tests/test_mk_parser.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from app.parsers.mk_parser import MKParser

MK_FILE = Path(
    "/Users/dinararisalieva/Desktop/Coworking/Расчет материалов и поиск поставщиков"
    "/Уплотнение/МК 01-04.26(1.(П4.05.00.280)1.4.1 - ЮПБ(испытания) (1).pdf"
)


@pytest.fixture(scope="module")
def result():
    parser = MKParser()
    return parser.parse(MK_FILE)


def test_file_readable(result):
    assert result.total_pages > 0


def test_mk_number_extracted(result):
    assert result.mk_number.status == "extracted"
    assert result.mk_number.value is not None
    print(f"\n  mk_number: {result.mk_number.value}")


def test_article_extracted(result):
    assert result.article.status == "extracted"
    print(f"\n  article: {result.article.value}")


def test_product_name_extracted(result):
    assert result.product_name.status == "extracted"
    print(f"\n  product_name: {result.product_name.value}")


def test_quantity_extracted(result):
    assert result.quantity.status == "extracted"
    assert result.quantity.value == 4.0
    print(f"\n  quantity: {result.quantity.value}")


def test_planned_materials_not_empty(result):
    assert len(result.planned_materials) > 0
    print(f"\n  planned_materials: {len(result.planned_materials)}")
    for m in result.planned_materials:
        print(f"    - {m.name.value} | {m.qty_per_unit.value} {m.unit.value}")


def test_planned_materials_known_items(result):
    names = [m.name.value for m in result.planned_materials if m.name.value]
    assert any("лист" in n.lower() for n in names), f"Лист не найден: {names}"
    assert any("резин" in n.lower() for n in names), f"Резина не найдена: {names}"


def test_operations_parsed(result):
    """Операции — опциональная секция МК (не все МК содержат таблицу операций).
    Проверяем что поле корректно инициализировано как список."""
    assert isinstance(result.operations, list)
    print(f"\n  operations: {len(result.operations)}")
    for op in result.operations:
        print(f"    {op.sequence}. {op.operation_name.value}")


def test_actual_materials_not_empty(result):
    assert len(result.actual_materials) > 0
    print(f"\n  actual_materials: {len(result.actual_materials)}")


def test_actual_vs_planned_names_match(result):
    planned_names = {m.name.value for m in result.planned_materials if m.name.value}
    actual_names  = {m.name.value for m in result.actual_materials  if m.name.value}
    overlap = planned_names & actual_names
    print(f"\n  planned={planned_names}, actual={actual_names}, overlap={overlap}")
    assert len(overlap) > 0, "Плановые и фактические материалы не пересекаются"


def test_confidence_above_threshold(result):
    print(f"\n  confidence: {result.confidence}")
    assert result.confidence >= 0.6, f"Confidence слишком низкий: {result.confidence}"


def test_no_critical_missing_fields(result):
    print(f"\n  missing_critical: {result.missing_critical_fields}")
    assert result.missing_critical_fields == [], (
        f"Критичные поля отсутствуют: {result.missing_critical_fields}"
    )


def test_parse_errors_empty(result):
    if result.parse_errors:
        print(f"\n  parse_errors: {result.parse_errors}")
    assert result.parse_errors == [], f"Ошибки парсинга: {result.parse_errors}"
