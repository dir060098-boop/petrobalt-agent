"""
Парсер маршрутных карт (МК) ООО "Петробалт Сервис".

Использует pdfplumber для извлечения таблиц из PDF.
Не требует AI — структура МК предсказуема и стабильна.

Поддерживаемая структура МК:
  Стр.1: заголовок, планируемые материалы, технология, инспекция
  Стр.2: фактические материалы, доп. материалы, масса
  Стр.3: лист маркировки, перечень упаковки
"""

from __future__ import annotations

import re
import logging
from pathlib import Path
from typing import Optional

import pdfplumber

from app.schemas.mk_schema import (
    MKParseResult,
    FieldValue,
    PlannedMaterial,
    AuxMaterial,
    Operation,
    InspectionItem,
    ActualMaterial,
    PackagingMaterial,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ключевые слова для определения таблиц
# ---------------------------------------------------------------------------

# Поиск по заголовку секции (merged row[0]) — для таблиц, где он есть
_TABLE_ACTUAL    = "фактически использованные"
_TABLE_AUX       = "доп"            # "Доп.материалы затраченные на производство"
_TABLE_MASS      = "масса готовой"
_TABLE_PACKAGING = "перечень используемых материалов"

# Поиск по заголовкам колонок (row[0] без merged-ячейки) — для таблиц без секции в row[0]
_COL_PLANNED     = "отпущенных"     # "вес материалов, отпущенных со склада" — уникален для плановых материалов
_COL_TECHNOLOGY  = "технолог"       # "Описание технологии" — уникален для операций
_COL_INSPECTION  = "инспекц"        # "Инспекция" — уникален для инспекции


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def _clean(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = v.strip().replace("\n", " ")
    return v if v else None


def _to_float(v: Optional[str]) -> Optional[float]:
    if not v:
        return None
    v = v.strip().replace(",", ".").replace(" ", "")
    try:
        return float(v)
    except ValueError:
        return None


def _extract_field(text: str, patterns: list) -> Optional[str]:
    """Ищет значение по списку регулярных выражений в тексте."""
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if m:
            return _clean(m.group(1))
    return None


def _table_col_matches(table: list, keyword: str) -> bool:
    """Проверяет, что строка с заголовками колонок содержит ключевое слово.
    Проверяем и row[0] и row[1] (на случай merged первой строки)."""
    if not table:
        return False
    kw = keyword.lower()
    for row in table[:2]:
        text = " ".join(str(c or "") for c in row).lower()
        if kw in text:
            return True
    return False


def _is_header_table(table: list) -> bool:
    """Определяет, является ли таблица заголовком МК (содержит Артикул + Наименование продукции)."""
    if len(table) < 2:
        return False
    # Проверяем row[0] или row[1] на наличие "артикул" + "наименование продукции"
    for row in table[:3]:
        text = " ".join(str(c or "") for c in row).lower()
        if "артикул" in text and "наименование" in text:
            return True
    return False


def _is_data_row(row: list) -> bool:
    """Пропускает пустые строки и строки-заголовки."""
    cells = [str(c or "").strip() for c in row]
    non_empty = [c for c in cells if c]
    return len(non_empty) >= 2


# ---------------------------------------------------------------------------
# Парсер заголовочной таблицы МК (Table 0 страница 1)
# ---------------------------------------------------------------------------

def _extract_from_header_table(table: list) -> tuple:
    """
    Из заголовочной таблицы МК извлекает product_name и quantity.
    Структура:
      row[0]: merged — компания + МК number + артикул
      row[1]: заголовки колонок: ['Артикул', 'Наименование продукции', ..., 'Ед.изм.', 'Кол-во', 'Комментарий']
      row[2]+: данные
    Возвращает (product_name, quantity_str)
    """
    if len(table) < 3:
        return None, None

    # Ищем строку с заголовками колонок
    header_row_idx = None
    for i, row in enumerate(table[:3]):
        text = " ".join(str(c or "") for c in row).lower()
        if "артикул" in text and ("наименование" in text or "кол-во" in text):
            header_row_idx = i
            break

    if header_row_idx is None:
        return None, None

    headers = [str(c or "").strip().lower() for c in table[header_row_idx]]

    # Ищем индексы нужных колонок
    name_col = None
    qty_col = None
    for i, h in enumerate(headers):
        if "наименование" in h and "продукц" in h:
            name_col = i
        # "кол-во" без "ед." (чтобы не спутать с "Кол-во на 1 ед.")
        if h in ("кол-во", "количество") or (h.startswith("кол") and "ед" not in h):
            qty_col = i

    # Берём данные из первой строки после заголовка
    data_row_idx = header_row_idx + 1
    if data_row_idx >= len(table):
        return None, None

    data_row = table[data_row_idx]

    product_name = None
    quantity_str = None

    if name_col is not None and name_col < len(data_row):
        product_name = _clean(str(data_row[name_col] or ""))

    if qty_col is not None and qty_col < len(data_row):
        quantity_str = _clean(str(data_row[qty_col] or ""))

    return product_name, quantity_str


# ---------------------------------------------------------------------------
# Парсеры отдельных таблиц
# ---------------------------------------------------------------------------

def _find_col_header_row(table: list) -> int:
    """
    Возвращает индекс строки с заголовками колонок.
    Пропускает merged-строки (например, "Материалы, фактически использованные").
    Критерий: строка содержит "№" или "наименование" и >=3 непустых ячейки.
    """
    for i, row in enumerate(table[:3]):
        cells = [str(c or "").strip() for c in row]
        non_empty = [c for c in cells if c]
        row_text = " ".join(non_empty).lower()
        if len(non_empty) >= 3 and ("№" in row_text or "наименование" in row_text or "п/п" in row_text):
            return i
    return 0


def _parse_planned_materials(table: list) -> list:
    results = []
    start = _find_col_header_row(table) + 1  # пропускаем заголовочную строку
    for row in table[start:]:
        if not _is_data_row(row):
            continue
        cells = [_clean(str(c or "")) for c in row]
        if len(cells) < 4:
            continue
        # Пропускаем строки-заголовки внутри таблицы
        first = (cells[0] or "").lower()
        if first in ("№", "№ п/п", "наименование", "п/п"):
            continue
        try:
            pos = int(cells[0]) if cells[0] and cells[0].isdigit() else None
        except (ValueError, AttributeError):
            pos = None

        name = cells[1] if len(cells) > 1 else None
        unit = cells[2] if len(cells) > 2 else None

        # Колонки 3,4,5 могут варьироваться — берём что есть
        qty_issued   = _to_float(cells[3]) if len(cells) > 3 else None
        qty_per_unit = _to_float(cells[4]) if len(cells) > 4 else None
        qty_total    = _to_float(cells[6]) if len(cells) > 6 else (
                       _to_float(cells[5]) if len(cells) > 5 else None)

        if not name:
            continue

        results.append(PlannedMaterial(
            position     = pos,
            name         = FieldValue.extracted(name),
            unit         = FieldValue.extracted(unit),
            qty_issued   = FieldValue.extracted(qty_issued),
            qty_per_unit = FieldValue.extracted(qty_per_unit),
            qty_total    = FieldValue.extracted(qty_total),
        ))
    return results


def _parse_operations(table: list) -> list:
    results = []
    start = _find_col_header_row(table) + 1
    for row in table[start:]:
        if not _is_data_row(row):
            continue
        cells = [_clean(str(c or "")) for c in row]
        if len(cells) < 2:
            continue
        first = (cells[0] or "").lower()
        if first in ("№", "№ п/п", "п/п"):
            continue
        try:
            seq = int(cells[0]) if cells[0] and cells[0].isdigit() else None
        except (ValueError, AttributeError):
            seq = None

        results.append(Operation(
            sequence         = seq,
            operation_name   = FieldValue.extracted(cells[1] if len(cells) > 1 else None),
            instruction_no   = FieldValue.extracted(cells[2] if len(cells) > 2 else None),
            department       = FieldValue.extracted(cells[3] if len(cells) > 3 else None),
            tech_description = FieldValue.extracted(cells[4] if len(cells) > 4 else None),
            comments         = FieldValue.extracted(cells[5] if len(cells) > 5 else None),
        ))
    return results


def _parse_inspection(table: list) -> list:
    results = []
    start = _find_col_header_row(table) + 1
    for row in table[start:]:
        if not _is_data_row(row):
            continue
        cells = [_clean(str(c or "")) for c in row]
        if len(cells) < 2:
            continue
        try:
            seq = int(cells[0]) if cells[0] and cells[0].isdigit() else None
        except (ValueError, AttributeError):
            seq = None

        results.append(InspectionItem(
            sequence       = seq,
            operation_name = FieldValue.extracted(cells[1] if len(cells) > 1 else None),
            instruction_no = FieldValue.extracted(cells[2] if len(cells) > 2 else None),
            department     = FieldValue.extracted(cells[3] if len(cells) > 3 else None),
            required_value = FieldValue.extracted(cells[4] if len(cells) > 4 else None),
            actual_value   = FieldValue.extracted(cells[5] if len(cells) > 5 else None),
            inspected_by   = FieldValue.extracted(cells[6] if len(cells) > 6 else None),
        ))
    return results


def _parse_actual_materials(table: list) -> list:
    results = []
    start = _find_col_header_row(table) + 1
    for row in table[start:]:
        if not _is_data_row(row):
            continue
        cells = [_clean(str(c or "")) for c in row]
        if len(cells) < 3:
            continue
        first = (cells[0] or "").lower()
        if first in ("№", "№ п/п", "п/п"):
            continue
        try:
            pos = int(cells[0]) if cells[0] and cells[0].isdigit() else None
        except (ValueError, AttributeError):
            pos = None

        name = cells[1] if len(cells) > 1 else None
        if not name:
            continue

        results.append(ActualMaterial(
            position     = pos,
            name         = FieldValue.extracted(name),
            unit         = FieldValue.extracted(cells[2] if len(cells) > 2 else None),
            qty_per_unit = FieldValue.extracted(_to_float(cells[3]) if len(cells) > 3 else None),
            qty_total    = FieldValue.extracted(_to_float(cells[4]) if len(cells) > 4 else None),
            qty_remainder= FieldValue.extracted(_to_float(cells[5]) if len(cells) > 5 else None),
            qty_returned = FieldValue.extracted(_to_float(cells[6]) if len(cells) > 6 else None),
            qty_recycled = FieldValue.extracted(_to_float(cells[7]) if len(cells) > 7 else None),
        ))
    return results


def _parse_aux_materials(table: list) -> list:
    results = []
    start = _find_col_header_row(table) + 1
    for row in table[start:]:
        if not _is_data_row(row):
            continue
        cells = [_clean(str(c or "")) for c in row]
        if len(cells) < 2:
            continue
        name = cells[1] if len(cells) > 1 else None
        if not name:
            continue
        try:
            pos = int(cells[0]) if cells[0] and cells[0].isdigit() else None
        except (ValueError, AttributeError):
            pos = None

        results.append(AuxMaterial(
            position     = pos,
            name         = FieldValue.extracted(name),
            unit         = FieldValue.extracted(cells[2] if len(cells) > 2 else None),
            qty_per_unit = FieldValue.extracted(_to_float(cells[3]) if len(cells) > 3 else None),
            qty_total    = FieldValue.extracted(_to_float(cells[4]) if len(cells) > 4 else None),
        ))
    return results


def _parse_packaging(table: list) -> list:
    results = []
    start = _find_col_header_row(table) + 1
    for row in table[start:]:
        if not _is_data_row(row):
            continue
        cells = [_clean(str(c or "")) for c in row]
        if len(cells) < 2:
            continue
        desc = cells[1] if len(cells) > 1 else None
        if not desc:
            continue
        try:
            pos = int(cells[0]) if cells[0] and cells[0].isdigit() else None
        except (ValueError, AttributeError):
            pos = None

        results.append(PackagingMaterial(
            position      = pos,
            description   = FieldValue.extracted(desc),
            material_type = FieldValue.extracted(cells[2] if len(cells) > 2 else None),
            unit          = FieldValue.extracted(cells[4] if len(cells) > 4 else None),
            qty           = FieldValue.extracted(_to_float(cells[5]) if len(cells) > 5 else None),
        ))
    return results


# ---------------------------------------------------------------------------
# Извлечение заголовка МК из текста страницы
# ---------------------------------------------------------------------------

def _parse_header(full_text: str) -> dict:
    """Извлекает поля заголовка МК из сырого текста."""

    mk_number = _extract_field(full_text, [
        r"Порядковый номер МК[:\s]+([0-9]{2}-[0-9]{2}\.[0-9]{2,4})",
        r"Номер МК[:\s]+([0-9]{2}-[0-9]{2}\.[0-9]{2,4})",
        r"МК[:\s]+([0-9]{2}-[0-9]{2}\.[0-9]{2,4})",
    ])

    article = _extract_field(full_text, [
        r"Артикул[:\s]+([\w\.\(\)]+)",
        r"[Аа]ртикул\s+([\w\.\(\)]+)",
    ])

    # date_start: поддерживаем "14.4.26", "14.04.2026", "14.04.26"
    date_start = _extract_field(full_text, [
        r"[Дд]ата\s+составления[:\s]+(\d{1,2}\.\d{1,2}\.\d{2,4})",
        r"[Дд]ата\s+начала[:\s]*производства[\s\S]{0,30}?(\d{1,2}\.\d{1,2}\.\d{2,4})",
        r"[Нн]ачало\s+производства[:\s]*(\d{1,2}\.\d{1,2}\.\d{2,4})",
        r"начала[:\s]+(\d{1,2}\.\d{1,2}\.\d{2,4})",
    ])

    date_end = _extract_field(full_text, [
        r"[Дд]ата\s+окончания[:\s]*производства[\s\S]{0,30}?(\d{1,2}\.\d{1,2}\.\d{2,4})",
        r"[Оо]кончание\s+производства[:\s]*(\d{1,2}\.\d{1,2}\.\d{2,4})",
        r"окончания[:\s]+(\d{1,2}\.\d{1,2}\.\d{2,4})",
    ])

    created_by = _extract_field(full_text, [
        r"Составил[:\s]+([А-ЯЁа-яё]+\s+[А-ЯЁ]\.[А-ЯЁ]\.)",
        r"Разработал[:\s]+([А-ЯЁа-яё]+\s+[А-ЯЁ]\.[А-ЯЁ]\.)",
    ])

    verified_by = _extract_field(full_text, [
        r"Проверил[:\s]+([А-ЯЁа-яё]+\s+[А-ЯЁ]\.[А-ЯЁ]\.)",
    ])

    return {
        "mk_number":  mk_number,
        "article":    article,
        "date_start": date_start,
        "date_end":   date_end,
        "created_by": created_by,
        "verified_by": verified_by,
    }


def _parse_mass(full_text: str) -> tuple:
    """Извлекает массу готовой продукции (до и после подрезки)."""
    values: list = []
    for m in re.finditer(r"(?:Значение|Масса)[,\s]*кг[\s\S]{0,60}?(\d+[,\.]?\d*)", full_text):
        v = _to_float(m.group(1))
        if v is not None:
            values.append(v)
    before = values[0] if len(values) > 0 else None
    after  = values[1] if len(values) > 1 else None
    return before, after


# ---------------------------------------------------------------------------
# Главный класс парсера
# ---------------------------------------------------------------------------

class MKParser:
    """
    Парсер маршрутных карт (МК) из PDF.
    Использует pdfplumber, не требует API.
    """

    def parse(self, file_path) -> MKParseResult:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        errors: list = []
        full_text = ""
        all_tables: list = []   # list of (label, table)

        # product_name и quantity берём из header-таблицы
        header_product_name: Optional[str] = None
        header_quantity: Optional[str] = None

        try:
            with pdfplumber.open(path) as pdf:
                total_pages = len(pdf.pages)
                for page_num, page in enumerate(pdf.pages, start=1):
                    page_text = page.extract_text() or ""
                    full_text += f"\n--- PAGE {page_num} ---\n{page_text}"

                    tables = page.extract_tables()
                    for table in tables:
                        if not table:
                            continue

                        # Заголовок строки — для определения типа таблицы
                        label = " ".join(str(c or "") for c in table[0]).lower()
                        all_tables.append((label, table))

                        # Сразу обрабатываем header-таблицу (страница 1)
                        if page_num == 1 and _is_header_table(table):
                            pn, qs = _extract_from_header_table(table)
                            if pn:
                                header_product_name = pn
                            if qs:
                                header_quantity = qs

        except Exception as e:
            errors.append(f"PDF read error: {e}")
            logger.error("MKParser: failed to read %s: %s", path, e)
            return MKParseResult(
                mk_number=FieldValue.missing(),
                article=FieldValue.missing(),
                product_name=FieldValue.missing(),
                quantity=FieldValue.missing(),
                quantity_unit=FieldValue.missing(),
                date_start=FieldValue.missing(),
                date_end=FieldValue.missing(),
                created_by=FieldValue.missing(),
                verified_by=FieldValue.missing(),
                mass_before_trim_kg=FieldValue.missing(),
                mass_after_trim_kg=FieldValue.missing(),
                parse_errors=[str(e)],
                confidence=0.0,
                raw_text="",
                total_pages=0,
            )

        # --- Парсинг заголовка из текста ---
        header = _parse_header(full_text)

        # --- Парсинг таблиц ---
        planned: list = []
        operations: list = []
        inspection: list = []
        actual: list = []
        aux: list = []
        packaging: list = []

        for label, table in all_tables:
            try:
                # Пропускаем header-таблицу
                if _is_header_table(table):
                    continue

                # Определяем тип по заголовку секции ИЛИ по заголовкам колонок
                if not planned and (
                    "планируемые к использованию" in label
                    or _table_col_matches(table, _COL_PLANNED)
                ):
                    planned = _parse_planned_materials(table)

                elif not operations and (
                    "технология" in label
                    or _table_col_matches(table, _COL_TECHNOLOGY)
                ):
                    operations = _parse_operations(table)

                elif not inspection and (
                    "инспекция" in label
                    or _table_col_matches(table, _COL_INSPECTION)
                ):
                    inspection = _parse_inspection(table)

                elif _TABLE_ACTUAL in label:
                    actual = _parse_actual_materials(table)

                elif _TABLE_AUX in label and "материал" in label:
                    aux = _parse_aux_materials(table)

                elif _TABLE_PACKAGING in label:
                    packaging = _parse_packaging(table)

            except Exception as e:
                errors.append(f"Table parse error [{label[:40]}]: {e}")
                logger.warning("MKParser: table parse error in %s: %s", path.name, e)

        # --- Масса ---
        mass_before, mass_after = _parse_mass(full_text)

        # --- Финальные значения ---
        # product_name: сначала из header-таблицы, затем из текста
        product_name = header_product_name or _extract_field(full_text, [
            r"Уплотн[её]ние\s+([\w\.\-]+)",
        ])

        # quantity: сначала из header-таблицы, затем из текста
        quantity = _to_float(header_quantity)

        result = MKParseResult(
            mk_number    = FieldValue.extracted(header["mk_number"]),
            article      = FieldValue.extracted(header["article"]),
            product_name = FieldValue.extracted(product_name),
            quantity     = FieldValue.extracted(quantity),
            quantity_unit= FieldValue.extracted("шт"),
            date_start   = FieldValue.extracted(header["date_start"]),
            date_end     = FieldValue.extracted(header["date_end"]),
            created_by   = FieldValue.extracted(header["created_by"]),
            verified_by  = FieldValue.extracted(header["verified_by"]),

            planned_materials   = planned,
            operations          = operations,
            inspection          = inspection,
            actual_materials    = actual,
            aux_materials       = aux,
            packaging_materials = packaging,

            mass_before_trim_kg = FieldValue.extracted(mass_before),
            mass_after_trim_kg  = FieldValue.extracted(mass_after),

            parse_errors = errors,
            raw_text     = full_text,
            total_pages  = total_pages,
        )

        result.compute_confidence()

        logger.info(
            "MKParser: parsed %s → mk=%s, confidence=%.2f, "
            "planned=%d, ops=%d, actual=%d, errors=%d",
            path.name,
            result.mk_number.value,
            result.confidence,
            len(planned),
            len(operations),
            len(actual),
            len(errors),
        )

        return result
