-- =============================================================================
-- SCHEMA v2.3: Агент расчёта материалов и поиска поставщиков
-- ООО "Петробалт Сервис" / ООО "Ендейвер"
-- Отрасль: производство биметаллических пластин, уплотнений, оборудования для буровых работ
-- База: PostgreSQL 15+ (Supabase)
--
-- Изменения v2.1 (технические исправления):
--   + updated_at добавлен в drawings, drawing_parts
--   + created_at добавлен во все промежуточные таблицы
--   + UNIQUE INDEX для price_history → ON CONFLICT DO NOTHING теперь работает
--   + PARTIAL UNIQUE INDEX для is_actual версий (drawings, route_cards)
--   + trg_sync_price_history берёт валюту из NEW.currency (quote_items), а не из quotes
--   + CHECK ограничения на положительные значения
--   + order_items.calculation_id убран (контролируется в backend через route_cards)
--   + drawing_parse_results — новая таблица для AI-парсера
--   + audit_log заполняется из backend-сервиса (не SQL-триггерами)
--
-- Изменения v2.2 (критические исправления):
--   FIX ON CONFLICT ON CONSTRAINT → ON CONFLICT (cols) WHERE ... DO NOTHING
--       (partial unique index ≠ named constraint — PostgreSQL не принимает имя индекса)
--   FIX AFTER-триггеры версий → BEFORE
--       (AFTER не успевает деактивировать старую версию до проверки partial unique index)
--   + supplier_regions — один поставщик в нескольких регионах
--   + индексы: dpr_parsed_at, dpr_confidence, drawings_actual, rc_actual, sreg_*
--
-- Изменения v2.3 (архитектурные дополнения):
--   + field_status расширен до 7 значений:
--     missing / extracted / calculated / manual / confirmed / rejected / not_applicable
--   + material_substitutes — допустимые аналоги материалов (только с явным разрешением)
--   + stock_balances — складские остатки (интеграция с 1С в будущем)
--   + purchase_requests + purchase_request_items — слой между расчётом и RFQ
--     BOM → проверка склада → заявка на закупку → только непокрытые позиции → RFQ
--   + rfq ссылается на purchase_request_id (не напрямую на calculations)
--   + v_quote_comparison — взвешенный скоринг вместо простого ранжирования по цене
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================================
-- МОДУЛЬ 0: ПОЛЬЗОВАТЕЛИ
-- =============================================================================

CREATE TABLE users (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    email               TEXT        NOT NULL UNIQUE,
    name                TEXT        NOT NULL,
    role                TEXT        NOT NULL DEFAULT 'viewer',
    -- admin / manager / viewer
    is_deleted          BOOL        NOT NULL DEFAULT FALSE,
    deleted_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT users_role_check CHECK (role IN ('admin', 'manager', 'viewer'))
);

COMMENT ON TABLE  users      IS 'Пользователи системы';
COMMENT ON COLUMN users.role IS 'admin — полный доступ, manager — расчёты и закупки, viewer — только просмотр';

-- =============================================================================
-- МОДУЛЬ 2: СПРАВОЧНИК МАТЕРИАЛОВ
-- (создаётся раньше изделий — на него ссылаются drawing_parts)
-- =============================================================================

CREATE TABLE materials (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                TEXT        NOT NULL,
    material_type       TEXT,
    -- sheet / bar / tube / pipe / rubber / wire / coating / other
    specification       TEXT,
    -- пример: "10*1500*6000"
    grade               TEXT,
    -- пример: "Ст3", "09Г2С", "Ст.20"
    standard            TEXT,
    -- пример: "ГОСТ 380-2005"
    category            TEXT        NOT NULL DEFAULT 'metal',
    -- metal / rubber / welding / packaging / chemical / other
    unit                TEXT        NOT NULL DEFAULT 'кг',
    density_kg_m3       NUMERIC,
    -- кг/м³: сталь ~7850, резина ~1200
    id_1c               TEXT,
    is_deleted          BOOL        NOT NULL DEFAULT FALSE,
    deleted_at          TIMESTAMPTZ,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT materials_category_check CHECK (
        category IN ('metal', 'rubber', 'welding', 'packaging', 'chemical', 'other')
    ),
    CONSTRAINT materials_type_check CHECK (
        material_type IS NULL OR
        material_type IN ('sheet', 'bar', 'tube', 'pipe', 'rubber', 'wire', 'coating', 'other')
    ),
    CONSTRAINT materials_density_pos CHECK (density_kg_m3 IS NULL OR density_kg_m3 > 0)
);

COMMENT ON TABLE materials       IS 'Справочник материалов';
COMMENT ON COLUMN materials.id_1c IS 'Номер в 1С — заполняется при интеграции';

-- =============================================================================
-- МОДУЛЬ 1: ИЗДЕЛИЯ И ЧЕРТЕЖИ
-- =============================================================================

CREATE TABLE products (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    article             TEXT        NOT NULL UNIQUE,
    name                TEXT        NOT NULL,
    drawing_number      TEXT,
    diameter_mm         NUMERIC,
    mass_kg             NUMERIC,
    unit                TEXT        NOT NULL DEFAULT 'шт',
    id_1c               TEXT,
    is_deleted          BOOL        NOT NULL DEFAULT FALSE,
    deleted_at          TIMESTAMPTZ,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT products_mass_pos     CHECK (mass_kg     IS NULL OR mass_kg     > 0),
    CONSTRAINT products_diameter_pos CHECK (diameter_mm IS NULL OR diameter_mm > 0)
);

COMMENT ON TABLE products IS 'Справочник изделий';


CREATE TABLE drawings (
    id                      UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    product_id              UUID        REFERENCES products(id) ON DELETE SET NULL,
    drawing_number          TEXT        NOT NULL,
    version                 TEXT        NOT NULL DEFAULT '1',
    is_actual               BOOL        NOT NULL DEFAULT TRUE,
    replaced_by_drawing_id  UUID        REFERENCES drawings(id) ON DELETE SET NULL,
    status                  TEXT        NOT NULL DEFAULT 'draft',
    -- draft / approved / archived
    drawing_type            TEXT        NOT NULL DEFAULT 'assembly',
    -- assembly / part / detail
    format                  TEXT,
    scale                   TEXT,
    developer               TEXT,
    approved_by             TEXT,
    organization            TEXT,
    drawing_date            DATE,
    file_path               TEXT,
    file_hash               TEXT,
    parse_status            TEXT        NOT NULL DEFAULT 'pending',
    -- pending / parsed / needs_review / failed
    parsed_at               TIMESTAMPTZ,
    parse_notes             TEXT,
    created_by              UUID        REFERENCES users(id) ON DELETE SET NULL,
    approved_by_user_id     UUID        REFERENCES users(id) ON DELETE SET NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT drawings_status_check  CHECK (status      IN ('draft', 'approved', 'archived')),
    CONSTRAINT drawings_type_check    CHECK (drawing_type IN ('assembly', 'part', 'detail')),
    CONSTRAINT drawings_parse_check   CHECK (parse_status IN ('pending', 'parsed', 'needs_review', 'failed'))
);

-- Гарантия: только один актуальный чертёж на drawing_number
CREATE UNIQUE INDEX uq_actual_drawing
    ON drawings(drawing_number)
    WHERE is_actual = TRUE;

COMMENT ON TABLE  drawings                        IS 'Чертежи изделий (PDF) с версионированием';
COMMENT ON COLUMN drawings.replaced_by_drawing_id IS 'Ссылка на новую версию (chain версий)';
COMMENT ON COLUMN drawings.file_hash              IS 'Хэш файла для предотвращения дублей при загрузке';


-- Результаты AI-парсинга чертежа (отдельная таблица для отладки)
CREATE TABLE drawing_parse_results (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    drawing_id          UUID        NOT NULL REFERENCES drawings(id) ON DELETE CASCADE,
    parse_version       TEXT,
    -- версия парсера / модели, например "claude-sonnet-4-6"
    extracted_text      TEXT,
    -- полный извлечённый текст
    extracted_dimensions JSONB,
    -- {"length": 380, "width": 305, "thickness": 10, ...}
    extracted_materials JSONB,
    -- [{"name": "Лист г/к", "grade": "Ст3", "standard": "ГОСТ 380-2005"}]
    extracted_stamp     JSONB,
    -- штамп чертежа: {"developer": "Монзиков", "approved": "Баёк", "mass": 3.02, ...}
    confidence          NUMERIC,
    -- 0.0 — 1.0
    errors              JSONB,
    -- [{"field": "grade", "message": "не найдено в тексте"}]
    missing_fields      TEXT[],
    -- поля, которые не удалось извлечь
    raw_response        TEXT,
    -- сырой ответ модели (для отладки)
    parsed_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT dpr_confidence_check CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1)
);

COMMENT ON TABLE drawing_parse_results IS 'Результаты AI-парсинга чертежа — для отладки и аудита распознавания';


CREATE TABLE drawing_parts (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    drawing_id          UUID        NOT NULL REFERENCES drawings(id) ON DELETE CASCADE,
    position            INT,
    part_number         TEXT,
    name                TEXT        NOT NULL,
    quantity            INT,
    material_id         UUID        REFERENCES materials(id) ON DELETE SET NULL,
    mass_kg             NUMERIC,
    standard            TEXT,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT dp_quantity_pos CHECK (quantity IS NULL OR quantity > 0),
    CONSTRAINT dp_mass_pos     CHECK (mass_kg  IS NULL OR mass_kg  > 0)
);

COMMENT ON TABLE drawing_parts IS 'Детали и материалы из спецификации сборочного чертежа';


CREATE TABLE product_materials (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    product_id          UUID        NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    material_id         UUID        NOT NULL REFERENCES materials(id) ON DELETE RESTRICT,
    qty_per_unit        NUMERIC     NOT NULL,
    -- норма расхода на 1 изделие (чистый вес)
    usage_norm          NUMERIC,
    -- норма с учётом отходов = qty_per_unit * waste_factor
    waste_factor        NUMERIC     NOT NULL DEFAULT 1.0,
    -- коэффициент отхода: 1.10 = 10% отхода
    unit                TEXT        NOT NULL DEFAULT 'кг',
    bom_type            TEXT        NOT NULL DEFAULT 'main',
    -- main / auxiliary / packaging
    field_status        TEXT        NOT NULL DEFAULT 'confirmed',
    -- missing / extracted / calculated / manual / confirmed / rejected / not_applicable
    source              TEXT,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(product_id, material_id),

    CONSTRAINT pm_bom_type_check    CHECK (bom_type    IN ('main', 'auxiliary', 'packaging')),
    CONSTRAINT pm_status_check      CHECK (field_status IN (
        'missing', 'extracted', 'calculated', 'manual', 'confirmed', 'rejected', 'not_applicable'
    )),
    CONSTRAINT pm_qty_pos           CHECK (qty_per_unit  > 0),
    CONSTRAINT pm_waste_factor_pos  CHECK (waste_factor >= 1.0)
);

COMMENT ON COLUMN product_materials.waste_factor IS '1.0 = без отхода, 1.15 = 15% (плазменная резка)';
COMMENT ON COLUMN product_materials.usage_norm   IS 'qty_per_unit × waste_factor — заполняется агентом';


CREATE TABLE product_operations (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    product_id          UUID        NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    sequence            INT         NOT NULL,
    operation_name      TEXT        NOT NULL,
    operation_type      TEXT,
    -- cutting / welding / bending / pressing / vulcanization / inspection / other
    instruction_no      TEXT,
    department          TEXT,
    machine_type        TEXT,
    executor            TEXT,
    tech_description    TEXT,
    norm_time_minutes   NUMERIC,
    cost_rate           NUMERIC,
    -- ₽/час
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(product_id, sequence),

    CONSTRAINT po_type_check          CHECK (
        operation_type IS NULL OR
        operation_type IN ('cutting', 'welding', 'bending', 'pressing', 'vulcanization', 'inspection', 'other')
    ),
    CONSTRAINT po_norm_time_pos       CHECK (norm_time_minutes IS NULL OR norm_time_minutes > 0),
    CONSTRAINT po_cost_rate_pos       CHECK (cost_rate         IS NULL OR cost_rate         > 0)
);

COMMENT ON TABLE product_operations IS 'Шаблон технологического процесса — копируется в МК при создании из заказа';


-- Допустимые аналоги материалов (только явно разрешённые — агент не заменяет сам)
CREATE TABLE material_substitutes (
    id                      UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    material_id             UUID        NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    -- исходный материал (из BOM)
    substitute_material_id  UUID        NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    -- допустимый аналог
    approved_by             UUID        REFERENCES users(id) ON DELETE SET NULL,
    approved_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    basis                   TEXT,
    -- основание: "ГОСТ 380 п.5.2", "решение главного инженера 14.04.26"
    is_active               BOOL        NOT NULL DEFAULT TRUE,
    notes                   TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(material_id, substitute_material_id),
    CHECK (material_id != substitute_material_id)
);

COMMENT ON TABLE  material_substitutes                    IS 'Допустимые аналоги материалов — агент предлагает замену только из этого списка';
COMMENT ON COLUMN material_substitutes.basis              IS 'Нормативное или административное основание замены';
COMMENT ON COLUMN material_substitutes.substitute_material_id IS 'Агент НЕ заменяет материал сам — только предлагает варианты из этой таблицы';

-- =============================================================================
-- МОДУЛЬ 3: ЗАКАЗЫ
-- =============================================================================

CREATE TABLE orders (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_number        TEXT        NOT NULL UNIQUE,
    client_name         TEXT        NOT NULL,
    client_inn          TEXT,
    order_date          DATE        NOT NULL DEFAULT CURRENT_DATE,
    delivery_date       DATE,
    priority            INT         NOT NULL DEFAULT 3,
    -- 1=срочно, 2=высокий, 3=обычный, 4=низкий
    status              TEXT        NOT NULL DEFAULT 'draft',
    -- draft / confirmed / in_production / completed / shipped / cancelled
    total_amount        NUMERIC,
    currency            TEXT        NOT NULL DEFAULT 'RUB',
    notes               TEXT,
    file_path           TEXT,
    file_hash           TEXT,
    is_deleted          BOOL        NOT NULL DEFAULT FALSE,
    deleted_at          TIMESTAMPTZ,
    created_by          UUID        REFERENCES users(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT orders_status_check   CHECK (status IN ('draft','confirmed','in_production','completed','shipped','cancelled')),
    CONSTRAINT orders_priority_check CHECK (priority BETWEEN 1 AND 4),
    CONSTRAINT orders_amount_pos     CHECK (total_amount IS NULL OR total_amount >= 0)
);

COMMENT ON COLUMN orders.priority IS '1=срочно, 2=высокий, 3=обычный, 4=низкий';


CREATE TABLE order_items (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id            UUID        NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id          UUID        NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    quantity            NUMERIC     NOT NULL,
    unit                TEXT        NOT NULL DEFAULT 'шт',
    price_per_unit      NUMERIC,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Примечание: связь order_item → calculation получается через route_cards.order_item_id
    -- Прямой FK order_items.calculation_id убран во избежание рассинхрона с route_cards

    CONSTRAINT oi_quantity_pos       CHECK (quantity       > 0),
    CONSTRAINT oi_price_pos          CHECK (price_per_unit IS NULL OR price_per_unit >= 0)
);

COMMENT ON TABLE order_items IS 'Позиции заказа. Связь с расчётом — через route_cards.order_item_id';

-- =============================================================================
-- МОДУЛЬ 4: МАРШРУТНЫЕ КАРТЫ
-- =============================================================================

CREATE TABLE route_cards (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    mk_number           TEXT        NOT NULL,
    version             INT         NOT NULL DEFAULT 1,
    is_actual           BOOL        NOT NULL DEFAULT TRUE,
    order_item_id       UUID        REFERENCES order_items(id) ON DELETE SET NULL,
    product_id          UUID        NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    quantity            NUMERIC     NOT NULL,
    quantity_actual     NUMERIC,
    mass_planned_kg     NUMERIC,
    mass_actual_kg      NUMERIC,
    date_start          DATE,
    date_end            DATE,
    created_by          TEXT,
    verified_by         TEXT,
    status              TEXT        NOT NULL DEFAULT 'draft',
    -- draft / confirmed / in_production / completed
    auto_calculated     BOOL        NOT NULL DEFAULT TRUE,
    file_path           TEXT,
    file_hash           TEXT,
    parse_status        TEXT        NOT NULL DEFAULT 'pending',
    -- pending / parsed / needs_review / confirmed / failed
    parsed_at           TIMESTAMPTZ,
    parse_notes         TEXT,
    is_deleted          BOOL        NOT NULL DEFAULT FALSE,
    deleted_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(mk_number, version),

    CONSTRAINT rc_status_check       CHECK (status       IN ('draft','confirmed','in_production','completed')),
    CONSTRAINT rc_parse_check        CHECK (parse_status IN ('pending','parsed','needs_review','confirmed','failed')),
    CONSTRAINT rc_quantity_pos       CHECK (quantity         > 0),
    CONSTRAINT rc_quantity_act_pos   CHECK (quantity_actual  IS NULL OR quantity_actual  >= 0),
    CONSTRAINT rc_mass_planned_pos   CHECK (mass_planned_kg  IS NULL OR mass_planned_kg  > 0),
    CONSTRAINT rc_mass_actual_pos    CHECK (mass_actual_kg   IS NULL OR mass_actual_kg   > 0)
);

-- Гарантия: только одна актуальная версия МК на mk_number
CREATE UNIQUE INDEX uq_actual_route_card
    ON route_cards(mk_number)
    WHERE is_actual = TRUE;

COMMENT ON TABLE  route_cards             IS 'Маршрутные карты производства с версионированием';
COMMENT ON COLUMN route_cards.is_actual   IS 'Только одна версия на mk_number — контролируется partial unique index';
COMMENT ON COLUMN route_cards.auto_calculated IS 'TRUE — МК создана агентом из заказа по нормам; FALSE — загружена вручную';


CREATE TABLE route_card_materials (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    route_card_id       UUID        NOT NULL REFERENCES route_cards(id) ON DELETE CASCADE,
    material_id         UUID        NOT NULL REFERENCES materials(id) ON DELETE RESTRICT,
    -- ПЛАН
    qty_per_unit        NUMERIC     NOT NULL,
    qty_total           NUMERIC     NOT NULL,
    -- ФАКТ
    qty_issued          NUMERIC,
    qty_remainder       NUMERIC,
    qty_recycled        NUMERIC,
    unit                TEXT        NOT NULL DEFAULT 'кг',
    bom_type            TEXT        NOT NULL DEFAULT 'main',
    -- main / auxiliary / packaging
    field_status        TEXT        NOT NULL DEFAULT 'calculated',
    -- missing / extracted / calculated / manual / confirmed / rejected / not_applicable
    source              TEXT,
    -- mk / drawing / manual / auto
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT rcm_bom_type_check  CHECK (bom_type    IN ('main','auxiliary','packaging')),
    CONSTRAINT rcm_status_check    CHECK (field_status IN (
        'missing', 'extracted', 'calculated', 'manual', 'confirmed', 'rejected', 'not_applicable'
    )),
    CONSTRAINT rcm_qty_per_pos     CHECK (qty_per_unit  > 0),
    CONSTRAINT rcm_qty_total_pos   CHECK (qty_total     > 0),
    CONSTRAINT rcm_qty_issued_pos  CHECK (qty_issued    IS NULL OR qty_issued    >= 0),
    CONSTRAINT rcm_qty_rem_pos     CHECK (qty_remainder IS NULL OR qty_remainder >= 0),
    CONSTRAINT rcm_qty_rec_pos     CHECK (qty_recycled  IS NULL OR qty_recycled  >= 0)
);

COMMENT ON COLUMN route_card_materials.field_status IS 'missing блокирует расчёт — агент не продолжает без подтверждения';


CREATE TABLE route_card_operations (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    route_card_id       UUID        NOT NULL REFERENCES route_cards(id) ON DELETE CASCADE,
    sequence            INT         NOT NULL,
    operation_name      TEXT        NOT NULL,
    operation_type      TEXT,
    -- cutting / welding / bending / pressing / vulcanization / inspection / other
    instruction_no      TEXT,
    department          TEXT,
    machine_type        TEXT,
    executor            TEXT,
    tech_description    TEXT,
    comments            TEXT,
    norm_time_minutes   NUMERIC,
    -- ИНСПЕКЦИЯ
    inspection_required BOOL        NOT NULL DEFAULT FALSE,
    inspection_method   TEXT,
    required_value      TEXT,
    actual_value        TEXT,
    inspected_by        TEXT,
    inspected_at        DATE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(route_card_id, sequence),

    CONSTRAINT rco_norm_time_pos CHECK (norm_time_minutes IS NULL OR norm_time_minutes > 0)
);

-- =============================================================================
-- МОДУЛЬ 5: РАСЧЁТЫ (snapshot — не пересчитывается при изменении цен)
-- =============================================================================

CREATE TABLE calculations (
    id                      UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    route_card_id           UUID        NOT NULL REFERENCES route_cards(id) ON DELETE CASCADE,
    status                  TEXT        NOT NULL DEFAULT 'pending',
    -- pending / verified / approved / rejected
    -- SNAPSHOT на момент расчёта
    snapshot_materials      JSONB,
    -- [{material_id, name, grade, qty, unit, unit_price, total}]
    snapshot_prices_date    DATE,
    -- ИТОГИ
    total_material_cost     NUMERIC,
    total_operation_cost    NUMERIC,
    total_cost              NUMERIC,
    margin                  NUMERIC,
    currency                TEXT        NOT NULL DEFAULT 'RUB',
    -- СТАТУС АГЕНТА
    agent_notes             TEXT,
    missing_fields          JSONB,
    -- [{"field": "grade", "material": "Круг 16", "status": "missing"}]
    -- ПОДТВЕРЖДЕНИЕ
    calculated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    calculated_by           TEXT,
    -- 'agent' или email пользователя
    approved_by             UUID        REFERENCES users(id) ON DELETE SET NULL,
    approved_at             TIMESTAMPTZ,
    rejected_reason         TEXT,

    CONSTRAINT calc_status_check         CHECK (status IN ('pending','verified','approved','rejected')),
    CONSTRAINT calc_material_cost_pos    CHECK (total_material_cost  IS NULL OR total_material_cost  >= 0),
    CONSTRAINT calc_operation_cost_pos   CHECK (total_operation_cost IS NULL OR total_operation_cost >= 0),
    CONSTRAINT calc_total_cost_pos       CHECK (total_cost           IS NULL OR total_cost           >= 0)
);

COMMENT ON TABLE  calculations                   IS 'Расчёт себестоимости — snapshot, не пересчитывается при изменении цен';
COMMENT ON COLUMN calculations.snapshot_materials IS 'JSON-слепок материалов и цен на момент расчёта';
COMMENT ON COLUMN calculations.missing_fields     IS 'Список missing-полей — блокирует переход к RFQ';

-- =============================================================================
-- МОДУЛЬ 6: ПОСТАВЩИКИ
-- =============================================================================

CREATE TABLE suppliers (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                TEXT        NOT NULL,
    inn                 TEXT        UNIQUE,
    supplier_type       TEXT        NOT NULL DEFAULT 'dealer',
    -- manufacturer / dealer / warehouse
    country             TEXT        NOT NULL DEFAULT 'RU',
    region              TEXT,
    city                TEXT,
    contact_person      TEXT,
    phone               TEXT,
    email               TEXT,
    website             TEXT,
    categories          TEXT[]      NOT NULL DEFAULT '{}',
    -- ["metal", "rubber", "welding"]
    is_verified         BOOL        NOT NULL DEFAULT FALSE,
    rating              INT,
    vat_included        BOOL,
    payment_terms       TEXT,
    incoterms           TEXT,
    delivery_days_min   INT,
    delivery_days_max   INT,
    min_order_rub       NUMERIC,
    last_contact_date   DATE,
    source              TEXT        NOT NULL DEFAULT 'own_db',
    -- own_db / web_search
    is_deleted          BOOL        NOT NULL DEFAULT FALSE,
    deleted_at          TIMESTAMPTZ,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT suppliers_type_check          CHECK (supplier_type IN ('manufacturer','dealer','warehouse')),
    CONSTRAINT suppliers_rating_check        CHECK (rating        IS NULL OR rating BETWEEN 1 AND 5),
    CONSTRAINT suppliers_source_check        CHECK (source        IN ('own_db','web_search')),
    CONSTRAINT suppliers_delivery_min_pos    CHECK (delivery_days_min IS NULL OR delivery_days_min >= 0),
    CONSTRAINT suppliers_delivery_max_pos    CHECK (delivery_days_max IS NULL OR delivery_days_max >= 0),
    CONSTRAINT suppliers_delivery_order      CHECK (
        delivery_days_min IS NULL OR delivery_days_max IS NULL OR
        delivery_days_min <= delivery_days_max
    ),
    CONSTRAINT suppliers_min_order_pos       CHECK (min_order_rub IS NULL OR min_order_rub >= 0)
);

COMMENT ON COLUMN suppliers.is_verified IS 'Проверенные поставщики из собственной базы имеют приоритет при поиске';
COMMENT ON COLUMN suppliers.incoterms   IS 'Базис поставки по Инкотермс 2020: EXW, FCA, DAP, DDP';


CREATE TABLE supplier_materials (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    supplier_id         UUID        NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    material_id         UUID        NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    last_price_rub      NUMERIC,
    last_price_date     DATE,
    min_order_qty       NUMERIC,
    unit                TEXT,
    lead_time_days      INT,
    in_stock            BOOL,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(supplier_id, material_id),

    CONSTRAINT sm_price_pos          CHECK (last_price_rub IS NULL OR last_price_rub >= 0),
    CONSTRAINT sm_min_order_pos      CHECK (min_order_qty  IS NULL OR min_order_qty  > 0),
    CONSTRAINT sm_lead_time_pos      CHECK (lead_time_days IS NULL OR lead_time_days >= 0)
);

COMMENT ON TABLE supplier_materials IS 'Что поставщик поставляет — текущая цена и условия';


-- Регионы работы поставщика (один поставщик — много регионов)
CREATE TABLE supplier_regions (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    supplier_id         UUID        NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    country             TEXT        NOT NULL DEFAULT 'RU',
    region              TEXT        NOT NULL,
    -- пример: "Татарстан", "Башкортостан", "Тюменская область"
    city                TEXT,
    -- уточнение до города если нужно
    is_primary          BOOL        NOT NULL DEFAULT FALSE,
    -- основной регион поставщика
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(supplier_id, country, region)
);

COMMENT ON TABLE  supplier_regions            IS 'Регионы работы поставщика — один поставщик может работать в нескольких регионах';
COMMENT ON COLUMN supplier_regions.is_primary IS 'TRUE = основной регион (головной офис / склад)';


-- Складские остатки (ручной ввод или синхронизация с 1С в будущем)
CREATE TABLE stock_balances (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    material_id         UUID        NOT NULL REFERENCES materials(id) ON DELETE RESTRICT,
    qty_available       NUMERIC     NOT NULL DEFAULT 0,
    unit                TEXT        NOT NULL DEFAULT 'кг',
    location            TEXT,
    -- склад / ячейка
    reserved_qty        NUMERIC     NOT NULL DEFAULT 0,
    -- зарезервировано под другие заказы
    last_updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by          UUID        REFERENCES users(id) ON DELETE SET NULL,
    source              TEXT        NOT NULL DEFAULT 'manual',
    -- manual / 1c_sync
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(material_id, location),

    CONSTRAINT sb_qty_pos      CHECK (qty_available >= 0),
    CONSTRAINT sb_reserved_pos CHECK (reserved_qty  >= 0),
    CONSTRAINT sb_source_check CHECK (source IN ('manual', '1c_sync'))
);

COMMENT ON TABLE  stock_balances              IS 'Складские остатки — основа для разделения BOM на "есть" и "купить"';
COMMENT ON COLUMN stock_balances.reserved_qty IS 'Зарезервировано под другие заказы — не учитывается как доступное';

-- =============================================================================
-- МОДУЛЬ 7: ИСТОРИЯ ЦЕН
-- =============================================================================

CREATE TABLE price_history (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    supplier_id         UUID        NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    material_id         UUID        NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    price               NUMERIC     NOT NULL,
    currency            TEXT        NOT NULL DEFAULT 'RUB',
    exchange_rate       NUMERIC     NOT NULL DEFAULT 1.0,
    price_rub           NUMERIC     GENERATED ALWAYS AS (price * exchange_rate) STORED,
    unit                TEXT        NOT NULL DEFAULT 'кг',
    vat_included        BOOL,
    recorded_at         DATE        NOT NULL DEFAULT CURRENT_DATE,
    source              TEXT        NOT NULL DEFAULT 'quote',
    -- quote / manual / web_search / catalog
    source_id           UUID,
    -- универсальная ссылка на источник (quote.id и т.п.)
    quote_id            UUID,
    -- FK → quotes (добавляется через ALTER ниже)
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ph_source_check        CHECK (source IN ('quote','manual','web_search','catalog')),
    CONSTRAINT ph_price_pos           CHECK (price          > 0),
    CONSTRAINT ph_exchange_rate_pos   CHECK (exchange_rate  > 0)
);

-- Уникальный индекс: не дублировать цену из одного КП для одного материала
-- ON CONFLICT DO NOTHING в триггере работает именно по этому индексу
CREATE UNIQUE INDEX uq_price_history_quote_item
    ON price_history (quote_id, material_id, supplier_id, recorded_at, currency)
    WHERE quote_id IS NOT NULL;

COMMENT ON TABLE  price_history           IS 'Полная история цен по каждому поставщику и материалу';
COMMENT ON COLUMN price_history.price_rub IS 'Автовычисляется: price × exchange_rate';

-- =============================================================================
-- МОДУЛЬ 7.5: ЗАКУПОЧНЫЕ ЗАЯВКИ
-- Слой между расчётом и RFQ.
-- BOM → проверка склада → заявка → только непокрытые позиции → RFQ
-- =============================================================================

CREATE TABLE purchase_requests (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    calculation_id      UUID        NOT NULL REFERENCES calculations(id) ON DELETE CASCADE,
    pr_number           TEXT        NOT NULL UNIQUE,
    -- пример: "ЗК-001-04.26"
    status              TEXT        NOT NULL DEFAULT 'draft',
    -- draft / approved / partially_ordered / completed / cancelled
    region              TEXT,
    -- регион поиска поставщиков
    priority            INT         NOT NULL DEFAULT 3,
    needed_by_date      DATE,
    -- срок поставки
    notes               TEXT,
    approved_by         UUID        REFERENCES users(id) ON DELETE SET NULL,
    approved_at         TIMESTAMPTZ,
    created_by          UUID        REFERENCES users(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT pr_status_check   CHECK (status IN ('draft','approved','partially_ordered','completed','cancelled')),
    CONSTRAINT pr_priority_check CHECK (priority BETWEEN 1 AND 4)
);

COMMENT ON TABLE purchase_requests IS 'Закупочная заявка — формируется из расчёта после проверки складских остатков';


CREATE TABLE purchase_request_items (
    id                      UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    purchase_request_id     UUID        NOT NULL REFERENCES purchase_requests(id) ON DELETE CASCADE,
    material_id             UUID        NOT NULL REFERENCES materials(id) ON DELETE RESTRICT,
    -- из BOM
    qty_required            NUMERIC     NOT NULL,
    -- сколько нужно по расчёту
    qty_in_stock            NUMERIC     NOT NULL DEFAULT 0,
    -- сколько покрывается складом (из stock_balances)
    qty_to_purchase         NUMERIC     GENERATED ALWAYS AS
                                (GREATEST(qty_required - qty_in_stock, 0)) STORED,
    -- сколько нужно купить
    unit                    TEXT        NOT NULL DEFAULT 'кг',
    substitute_material_id  UUID        REFERENCES materials(id) ON DELETE SET NULL,
    -- выбранный аналог (из material_substitutes, только если пользователь выбрал)
    status                  TEXT        NOT NULL DEFAULT 'pending',
    -- pending / in_stock / ordered / received / cancelled
    notes                   TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT pri_qty_req_pos    CHECK (qty_required   > 0),
    CONSTRAINT pri_qty_stock_pos  CHECK (qty_in_stock  >= 0),
    CONSTRAINT pri_status_check   CHECK (status IN ('pending','in_stock','ordered','received','cancelled'))
);

COMMENT ON TABLE  purchase_request_items                       IS 'Позиции закупочной заявки с разбивкой: склад vs купить';
COMMENT ON COLUMN purchase_request_items.qty_to_purchase       IS 'Автовычисляется: max(qty_required − qty_in_stock, 0)';
COMMENT ON COLUMN purchase_request_items.substitute_material_id IS 'Только явный выбор пользователя из material_substitutes — агент не подставляет сам';

-- =============================================================================
-- МОДУЛЬ 8: RFQ И КОММЕРЧЕСКИЕ ПРЕДЛОЖЕНИЯ
-- =============================================================================

CREATE TABLE rfq (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    purchase_request_id UUID        NOT NULL REFERENCES purchase_requests(id) ON DELETE CASCADE,
    -- RFQ создаётся из закупочной заявки, не напрямую из расчёта
    status              TEXT        NOT NULL DEFAULT 'draft',
    -- draft / sent / partially_received / closed / cancelled
    due_date            DATE,
    rfq_text            TEXT,
    created_by          UUID        REFERENCES users(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at             TIMESTAMPTZ,
    closed_at           TIMESTAMPTZ,

    CONSTRAINT rfq_status_check CHECK (status IN ('draft','sent','partially_received','closed','cancelled'))
);

COMMENT ON TABLE rfq IS 'RFQ-запросы коммерческих предложений';


CREATE TABLE rfq_items (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    rfq_id              UUID        NOT NULL REFERENCES rfq(id) ON DELETE CASCADE,
    material_id         UUID        NOT NULL REFERENCES materials(id) ON DELETE RESTRICT,
    qty_required        NUMERIC     NOT NULL,
    unit                TEXT        NOT NULL DEFAULT 'кг',
    required_grade      TEXT,
    required_standard   TEXT,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ri_qty_pos CHECK (qty_required > 0)
);

COMMENT ON TABLE rfq_items IS 'Позиции RFQ — что запрашиваем у поставщиков';


CREATE TABLE rfq_suppliers (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    rfq_id              UUID        NOT NULL REFERENCES rfq(id) ON DELETE CASCADE,
    supplier_id         UUID        NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    status              TEXT        NOT NULL DEFAULT 'pending',
    -- pending / sent / responded / no_response / declined
    sent_at             TIMESTAMPTZ,
    responded_at        TIMESTAMPTZ,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(rfq_id, supplier_id),

    CONSTRAINT rfqs_status_check CHECK (status IN ('pending','sent','responded','no_response','declined'))
);


CREATE TABLE quotes (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    rfq_id              UUID        NOT NULL REFERENCES rfq(id) ON DELETE CASCADE,
    supplier_id         UUID        NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    received_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_until         DATE,
    total_amount        NUMERIC,
    currency            TEXT        NOT NULL DEFAULT 'RUB',
    vat_included        BOOL,
    delivery_days       INT,
    delivery_terms      TEXT,
    payment_terms       TEXT,
    incoterms           TEXT,
    notes               TEXT,
    file_path           TEXT,
    file_hash           TEXT,
    status              TEXT        NOT NULL DEFAULT 'received',
    -- received / accepted / rejected / expired
    comparison_rank     INT,
    comparison_notes    TEXT,

    CONSTRAINT quotes_status_check     CHECK (status IN ('received','accepted','rejected','expired')),
    CONSTRAINT quotes_amount_pos       CHECK (total_amount  IS NULL OR total_amount  >= 0),
    CONSTRAINT quotes_delivery_pos     CHECK (delivery_days IS NULL OR delivery_days >= 0),
    CONSTRAINT quotes_rank_pos         CHECK (comparison_rank IS NULL OR comparison_rank > 0)
);

COMMENT ON COLUMN quotes.comparison_rank IS '1 = лучшее предложение по итогам сравнения агентом';


CREATE TABLE quote_items (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    quote_id            UUID        NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
    material_id         UUID        NOT NULL REFERENCES materials(id) ON DELETE RESTRICT,
    qty                 NUMERIC     NOT NULL,
    unit                TEXT        NOT NULL DEFAULT 'кг',
    unit_price          NUMERIC,
    total_price         NUMERIC,
    currency            TEXT        NOT NULL DEFAULT 'RUB',
    -- валюта позиции (может отличаться от валюты КП в целом)
    in_stock            BOOL,
    lead_time_days      INT,
    moq                 NUMERIC,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT qi_qty_pos          CHECK (qty        > 0),
    CONSTRAINT qi_unit_price_pos   CHECK (unit_price IS NULL OR unit_price >= 0),
    CONSTRAINT qi_total_price_pos  CHECK (total_price IS NULL OR total_price >= 0),
    CONSTRAINT qi_lead_time_pos    CHECK (lead_time_days IS NULL OR lead_time_days >= 0),
    CONSTRAINT qi_moq_pos          CHECK (moq        IS NULL OR moq        > 0)
);

COMMENT ON COLUMN quote_items.currency IS 'Валюта конкретной позиции — используется в триггере price_history';

-- =============================================================================
-- МОДУЛЬ 9: AUDIT LOG
-- Заполняется из backend-сервиса (FastAPI), не SQL-триггерами.
-- SQL-триггеры аудита создают избыточную нагрузку и сложность.
-- Backend пишет в audit_log явно при каждом изменении через сервисный слой.
-- =============================================================================

CREATE TABLE audit_log (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    table_name          TEXT        NOT NULL,
    record_id           UUID        NOT NULL,
    action              TEXT        NOT NULL,
    -- INSERT / UPDATE / DELETE
    old_data            JSONB,
    new_data            JSONB,
    changed_fields      TEXT[],
    -- список изменённых полей при UPDATE
    changed_by          UUID        REFERENCES users(id) ON DELETE SET NULL,
    changed_by_label    TEXT,
    -- 'agent' или email — сохраняется на случай удаления пользователя
    ip_address          TEXT,
    changed_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT audit_action_check CHECK (action IN ('INSERT','UPDATE','DELETE'))
);

COMMENT ON TABLE  audit_log              IS 'Журнал изменений — заполняется из backend-сервиса (FastAPI)';
COMMENT ON COLUMN audit_log.changed_fields IS 'Только при UPDATE — какие поля изменились';

-- =============================================================================
-- ОТЛОЖЕННЫЕ FOREIGN KEYS
-- =============================================================================

-- price_history → quotes (quotes создаётся после price_history)
ALTER TABLE price_history
    ADD CONSTRAINT fk_price_history_quote
    FOREIGN KEY (quote_id) REFERENCES quotes(id) ON DELETE SET NULL;

-- =============================================================================
-- ИНДЕКСЫ
-- =============================================================================

-- Пользователи
CREATE INDEX idx_users_email            ON users(email);
CREATE INDEX idx_users_is_deleted       ON users(is_deleted);

-- Изделия
CREATE INDEX idx_products_article       ON products(article);
CREATE INDEX idx_products_drawing_no    ON products(drawing_number);
CREATE INDEX idx_products_is_deleted    ON products(is_deleted);

-- Чертежи
CREATE INDEX idx_drawings_product_id    ON drawings(product_id);
CREATE INDEX idx_drawings_status        ON drawings(status);
CREATE INDEX idx_drawings_file_hash     ON drawings(file_hash);
CREATE INDEX idx_drawings_parse_status  ON drawings(parse_status);
CREATE INDEX idx_dpr_drawing_id         ON drawing_parse_results(drawing_id);

-- Детали чертежей
CREATE INDEX idx_dp_drawing_id          ON drawing_parts(drawing_id);
CREATE INDEX idx_dp_material_id         ON drawing_parts(material_id);

-- Материалы
CREATE INDEX idx_materials_category     ON materials(category);
CREATE INDEX idx_materials_grade        ON materials(grade);
CREATE INDEX idx_materials_type         ON materials(material_type);
CREATE INDEX idx_materials_is_deleted   ON materials(is_deleted);

-- Нормы BOM
CREATE INDEX idx_pm_product_id          ON product_materials(product_id);
CREATE INDEX idx_pm_material_id         ON product_materials(material_id);
CREATE INDEX idx_pm_field_status        ON product_materials(field_status);
CREATE INDEX idx_po_product_id          ON product_operations(product_id);

-- Заказы
CREATE INDEX idx_orders_status          ON orders(status);
CREATE INDEX idx_orders_priority        ON orders(priority);
CREATE INDEX idx_orders_delivery_date   ON orders(delivery_date);
CREATE INDEX idx_orders_client_inn      ON orders(client_inn);
CREATE INDEX idx_orders_is_deleted      ON orders(is_deleted);
CREATE INDEX idx_oi_order_id            ON order_items(order_id);
CREATE INDEX idx_oi_product_id          ON order_items(product_id);

-- МК
CREATE INDEX idx_rc_mk_number           ON route_cards(mk_number);
CREATE INDEX idx_rc_status              ON route_cards(status);
CREATE INDEX idx_rc_product_id          ON route_cards(product_id);
CREATE INDEX idx_rc_order_item_id       ON route_cards(order_item_id);
CREATE INDEX idx_rc_is_deleted          ON route_cards(is_deleted);
CREATE INDEX idx_rcm_route_card_id      ON route_card_materials(route_card_id);
CREATE INDEX idx_rcm_material_id        ON route_card_materials(material_id);
CREATE INDEX idx_rcm_field_status       ON route_card_materials(field_status);
CREATE INDEX idx_rco_route_card_id      ON route_card_operations(route_card_id);

-- Расчёты
CREATE INDEX idx_calc_status            ON calculations(status);
CREATE INDEX idx_calc_route_card_id     ON calculations(route_card_id);
CREATE INDEX idx_calc_approved_at       ON calculations(approved_at);

-- Поставщики
CREATE INDEX idx_suppliers_region       ON suppliers(region);
CREATE INDEX idx_suppliers_country      ON suppliers(country);
CREATE INDEX idx_suppliers_type         ON suppliers(supplier_type);
CREATE INDEX idx_suppliers_is_verified  ON suppliers(is_verified);
CREATE INDEX idx_suppliers_is_deleted   ON suppliers(is_deleted);
CREATE INDEX idx_suppliers_categories   ON suppliers USING GIN(categories);
CREATE INDEX idx_sm_supplier_id         ON supplier_materials(supplier_id);
CREATE INDEX idx_sm_material_id         ON supplier_materials(material_id);

-- История цен
CREATE INDEX idx_ph_supplier_id         ON price_history(supplier_id);
CREATE INDEX idx_ph_material_id         ON price_history(material_id);
CREATE INDEX idx_ph_recorded_at         ON price_history(recorded_at);
CREATE INDEX idx_ph_sm_date             ON price_history(supplier_id, material_id, recorded_at DESC);
CREATE INDEX idx_ph_currency            ON price_history(currency);

-- RFQ и КП
CREATE INDEX idx_rfq_status             ON rfq(status);
CREATE INDEX idx_rfq_calculation_id     ON rfq(calculation_id);
CREATE INDEX idx_rfq_items_rfq_id       ON rfq_items(rfq_id);
CREATE INDEX idx_rfqs_rfq_id            ON rfq_suppliers(rfq_id);
CREATE INDEX idx_rfqs_supplier_id       ON rfq_suppliers(supplier_id);
CREATE INDEX idx_quotes_rfq_id          ON quotes(rfq_id);
CREATE INDEX idx_quotes_supplier_id     ON quotes(supplier_id);
CREATE INDEX idx_quotes_status          ON quotes(status);
CREATE INDEX idx_quotes_valid_until     ON quotes(valid_until);
CREATE INDEX idx_qi_quote_id            ON quote_items(quote_id);
CREATE INDEX idx_qi_material_id         ON quote_items(material_id);

-- drawing_parse_results
CREATE INDEX idx_dpr_parsed_at          ON drawing_parse_results(parsed_at DESC);
CREATE INDEX idx_dpr_confidence         ON drawing_parse_results(confidence);

-- Составные индексы для версионирования (быстрый поиск актуальной версии)
CREATE INDEX idx_drawings_actual        ON drawings(drawing_number, is_actual);
CREATE INDEX idx_rc_actual              ON route_cards(mk_number, is_actual);

-- supplier_regions
CREATE INDEX idx_sreg_supplier_id       ON supplier_regions(supplier_id);
CREATE INDEX idx_sreg_region            ON supplier_regions(country, region);

-- material_substitutes
CREATE INDEX idx_msub_material_id       ON material_substitutes(material_id);
CREATE INDEX idx_msub_substitute_id     ON material_substitutes(substitute_material_id);
CREATE INDEX idx_msub_is_active         ON material_substitutes(is_active);

-- stock_balances
CREATE INDEX idx_sb_material_id         ON stock_balances(material_id);
CREATE INDEX idx_sb_location            ON stock_balances(location);

-- purchase_requests
CREATE INDEX idx_pr_calculation_id      ON purchase_requests(calculation_id);
CREATE INDEX idx_pr_status              ON purchase_requests(status);
CREATE INDEX idx_pr_needed_by           ON purchase_requests(needed_by_date);

-- purchase_request_items
CREATE INDEX idx_pri_pr_id              ON purchase_request_items(purchase_request_id);
CREATE INDEX idx_pri_material_id        ON purchase_request_items(material_id);
CREATE INDEX idx_pri_status             ON purchase_request_items(status);

-- rfq → purchase_request
CREATE INDEX idx_rfq_pr_id              ON rfq(purchase_request_id);

-- Audit log
CREATE INDEX idx_audit_table_record     ON audit_log(table_name, record_id);
CREATE INDEX idx_audit_changed_at       ON audit_log(changed_at DESC);
CREATE INDEX idx_audit_changed_by       ON audit_log(changed_by);

-- =============================================================================
-- ПРЕДСТАВЛЕНИЯ (VIEWS)
-- =============================================================================

-- Актуальная цена (последняя) по каждому поставщику и материалу
CREATE VIEW v_current_prices AS
SELECT DISTINCT ON (ph.supplier_id, ph.material_id)
    ph.supplier_id,
    ph.material_id,
    s.name              AS supplier_name,
    s.region,
    s.country,
    s.is_verified,
    s.supplier_type,
    m.name              AS material_name,
    m.grade,
    m.specification,
    m.standard,
    m.category,
    ph.price            AS price_original,
    ph.currency,
    ph.price_rub,
    ph.unit,
    ph.vat_included,
    ph.recorded_at,
    ph.source
FROM price_history ph
JOIN suppliers s ON s.id = ph.supplier_id AND s.is_deleted = FALSE
JOIN materials m ON m.id = ph.material_id AND m.is_deleted = FALSE
ORDER BY ph.supplier_id, ph.material_id, ph.recorded_at DESC;

COMMENT ON VIEW v_current_prices IS 'Последняя известная цена каждого поставщика по каждому материалу в рублях';


-- Динамика цен за 90 дней с % изменения
CREATE VIEW v_price_dynamics AS
SELECT
    m.name                  AS material_name,
    m.grade,
    m.specification,
    s.name                  AS supplier_name,
    s.region,
    s.is_verified,
    ph.price_rub,
    ph.currency,
    ph.recorded_at,
    ph.source,
    LAG(ph.price_rub) OVER w                AS prev_price_rub,
    ROUND(
        (ph.price_rub - LAG(ph.price_rub) OVER w)
        / NULLIF(LAG(ph.price_rub) OVER w, 0) * 100
    , 2)                                    AS change_pct,
    ph.recorded_at - LAG(ph.recorded_at) OVER w AS days_since_prev
FROM price_history ph
JOIN materials m ON m.id = ph.material_id
JOIN suppliers s ON s.id = ph.supplier_id
WHERE ph.recorded_at >= CURRENT_DATE - INTERVAL '90 days'
WINDOW w AS (PARTITION BY ph.supplier_id, ph.material_id ORDER BY ph.recorded_at);

COMMENT ON VIEW v_price_dynamics IS 'Динамика цен за 90 дней с % изменения';


-- Сводный статус заказа: от позиции до МК и расчёта
CREATE VIEW v_order_status AS
SELECT
    o.order_number,
    o.client_name,
    o.order_date,
    o.delivery_date,
    o.priority,
    o.status                AS order_status,
    oi.id                   AS order_item_id,
    p.article,
    p.name                  AS product_name,
    oi.quantity             AS ordered_qty,
    rc.mk_number,
    rc.version              AS mk_version,
    rc.quantity_actual      AS produced_qty,
    rc.status               AS mk_status,
    rc.date_start,
    rc.date_end,
    calc.status             AS calc_status,
    calc.total_material_cost,
    calc.total_operation_cost,
    calc.total_cost,
    calc.missing_fields
FROM orders o
JOIN order_items oi        ON oi.order_id      = o.id
JOIN products p            ON p.id             = oi.product_id
LEFT JOIN route_cards rc   ON rc.order_item_id = oi.id  AND rc.is_actual = TRUE
LEFT JOIN calculations calc ON calc.route_card_id = rc.id
WHERE o.is_deleted = FALSE;

COMMENT ON VIEW v_order_status IS 'Сводный статус заказа от позиции до МК и расчёта';


-- Сравнение КП по одному RFQ с взвешенным скорингом
-- Скоринг (меньше = лучше, итоговый ранг по score_total):
--   цена          40% — нормализованная позиция по цене
--   срок          25% — нормализованная позиция по delivery_days
--   верификация   15% — is_verified поставщика (0 = проверен, 1 = нет)
--   НДС           10% — vat_included (0 = с НДС удобнее для зачёта, 1 = без)
--   тип           10% — manufacturer лучше dealer, dealer лучше warehouse
CREATE VIEW v_quote_comparison AS
WITH ranked AS (
    SELECT
        r.id                    AS rfq_id,
        q.id                    AS quote_id,
        s.name                  AS supplier_name,
        s.region,
        s.country,
        s.is_verified,
        s.supplier_type,
        s.rating,
        q.total_amount,
        q.currency,
        q.vat_included,
        q.delivery_days,
        q.delivery_terms,
        q.payment_terms,
        q.incoterms,
        q.valid_until,
        q.status,
        COUNT(qi.id)            AS items_count,
        -- ранги по отдельным критериям
        RANK() OVER (PARTITION BY r.id ORDER BY q.total_amount   ASC  NULLS LAST) AS price_rank,
        RANK() OVER (PARTITION BY r.id ORDER BY q.delivery_days  ASC  NULLS LAST) AS lead_time_rank,
        COUNT(*) OVER (PARTITION BY r.id)                                          AS total_quotes,
        q.comparison_notes
    FROM rfq r
    JOIN quotes q            ON q.rfq_id     = r.id
    JOIN suppliers s         ON s.id         = q.supplier_id
    LEFT JOIN quote_items qi ON qi.quote_id  = q.id
    GROUP BY r.id, q.id, s.name, s.region, s.country, s.is_verified,
             s.supplier_type, s.rating, q.total_amount, q.currency,
             q.vat_included, q.delivery_days, q.delivery_terms,
             q.payment_terms, q.incoterms, q.valid_until,
             q.status, q.comparison_notes
)
SELECT
    *,
    -- взвешенный скоринг (0.0 = лучший)
    ROUND(
        0.40 * (price_rank::NUMERIC    / NULLIF(total_quotes, 0))
      + 0.25 * (lead_time_rank::NUMERIC / NULLIF(total_quotes, 0))
      + 0.15 * CASE WHEN is_verified    THEN 0 ELSE 1 END
      + 0.10 * CASE WHEN vat_included   THEN 0 ELSE 1 END
      + 0.10 * CASE supplier_type
                   WHEN 'manufacturer' THEN 0.0
                   WHEN 'dealer'       THEN 0.5
                   ELSE                     1.0 END
    , 3)                            AS score_total,
    -- итоговый ранг по скорингу
    RANK() OVER (
        PARTITION BY rfq_id
        ORDER BY (
            0.40 * (price_rank::NUMERIC    / NULLIF(total_quotes, 0))
          + 0.25 * (lead_time_rank::NUMERIC / NULLIF(total_quotes, 0))
          + 0.15 * CASE WHEN is_verified  THEN 0 ELSE 1 END
          + 0.10 * CASE WHEN vat_included THEN 0 ELSE 1 END
          + 0.10 * CASE supplier_type
                       WHEN 'manufacturer' THEN 0.0
                       WHEN 'dealer'       THEN 0.5
                       ELSE                     1.0 END
        ) ASC
    )                               AS optimal_rank
FROM ranked;

COMMENT ON VIEW v_quote_comparison IS
    'Сравнение КП: score_total — взвешенный скоринг (меньше = лучше). '
    'optimal_rank=1 — оптимальное по совокупности: цена 40%, срок 25%, верификация 15%, НДС 10%, тип поставщика 10%';


-- Поля со статусом missing — блокируют расчёт
CREATE VIEW v_missing_fields AS
SELECT
    rc.mk_number,
    rc.version          AS mk_version,
    p.article,
    p.name              AS product_name,
    m.name              AS material_name,
    m.grade,
    rcm.field_status,
    rcm.notes,
    rc.status           AS mk_status,
    rc.created_at
FROM route_card_materials rcm
JOIN route_cards rc ON rc.id = rcm.route_card_id AND rc.is_deleted = FALSE
JOIN products p     ON p.id  = rc.product_id
JOIN materials m    ON m.id  = rcm.material_id
WHERE rcm.field_status = 'missing'
ORDER BY rc.created_at DESC;

COMMENT ON VIEW v_missing_fields IS 'Все незаполненные обязательные поля — блокируют расчёт и RFQ';

-- =============================================================================
-- ТРИГГЕРЫ: updated_at
-- =============================================================================

CREATE OR REPLACE FUNCTION trg_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
CREATE TRIGGER trg_products_updated_at
    BEFORE UPDATE ON products FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
CREATE TRIGGER trg_materials_updated_at
    BEFORE UPDATE ON materials FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
CREATE TRIGGER trg_drawings_updated_at
    BEFORE UPDATE ON drawings FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
CREATE TRIGGER trg_drawing_parts_updated_at
    BEFORE UPDATE ON drawing_parts FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
CREATE TRIGGER trg_product_materials_updated_at
    BEFORE UPDATE ON product_materials FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
CREATE TRIGGER trg_product_operations_updated_at
    BEFORE UPDATE ON product_operations FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
CREATE TRIGGER trg_orders_updated_at
    BEFORE UPDATE ON orders FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
CREATE TRIGGER trg_route_cards_updated_at
    BEFORE UPDATE ON route_cards FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
CREATE TRIGGER trg_rcm_updated_at
    BEFORE UPDATE ON route_card_materials FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
CREATE TRIGGER trg_rco_updated_at
    BEFORE UPDATE ON route_card_operations FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
CREATE TRIGGER trg_suppliers_updated_at
    BEFORE UPDATE ON suppliers FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
CREATE TRIGGER trg_supplier_materials_updated_at
    BEFORE UPDATE ON supplier_materials FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

-- =============================================================================
-- ТРИГГЕР: автоматическая деактивация предыдущей версии чертежа
-- =============================================================================

CREATE OR REPLACE FUNCTION trg_deactivate_prev_drawing_version()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.is_actual = TRUE THEN
        UPDATE drawings
        SET is_actual = FALSE
        WHERE drawing_number = NEW.drawing_number AND id != NEW.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_drawings_version
    BEFORE INSERT OR UPDATE OF is_actual ON drawings
    FOR EACH ROW EXECUTE FUNCTION trg_deactivate_prev_drawing_version();

-- =============================================================================
-- ТРИГГЕР: автоматическая деактивация предыдущей версии МК
-- =============================================================================

CREATE OR REPLACE FUNCTION trg_deactivate_prev_mk_version()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.is_actual = TRUE THEN
        UPDATE route_cards
        SET is_actual = FALSE
        WHERE mk_number = NEW.mk_number AND id != NEW.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_route_cards_version
    BEFORE INSERT OR UPDATE OF is_actual ON route_cards
    FOR EACH ROW EXECUTE FUNCTION trg_deactivate_prev_mk_version();

-- =============================================================================
-- ТРИГГЕР: запись в price_history при добавлении позиции КП
-- Исправлено: валюта берётся из NEW.currency (quote_items), а не из quotes.currency
-- Дубли предотвращаются через uq_price_history_quote_item
-- =============================================================================

CREATE OR REPLACE FUNCTION trg_sync_price_history()
RETURNS TRIGGER AS $$
DECLARE
    v_quote quotes%ROWTYPE;
BEGIN
    IF NEW.unit_price IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT * INTO v_quote FROM quotes WHERE id = NEW.quote_id;

    INSERT INTO price_history (
        supplier_id, material_id,
        price, currency, exchange_rate,
        unit, vat_included,
        recorded_at, source, source_id, quote_id
    ) VALUES (
        v_quote.supplier_id,
        NEW.material_id,
        NEW.unit_price,
        NEW.currency,               -- валюта из позиции КП
        1.0,                        -- TODO: подставлять курс из внешнего сервиса при currency != 'RUB'
        NEW.unit,
        v_quote.vat_included,
        v_quote.received_at::DATE,
        'quote',
        v_quote.id,
        v_quote.id
    )
    ON CONFLICT (quote_id, material_id, supplier_id, recorded_at, currency)
    WHERE quote_id IS NOT NULL
    DO NOTHING;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_quote_items_price_history
    AFTER INSERT ON quote_items
    FOR EACH ROW EXECUTE FUNCTION trg_sync_price_history();

COMMENT ON TRIGGER trg_quote_items_price_history ON quote_items
    IS 'При добавлении позиции КП автоматически фиксирует цену в price_history. Дубли исключены через UNIQUE INDEX.';

-- =============================================================================
-- СПРАВОЧНЫЕ ДАННЫЕ: базовые материалы из реальных МК
-- =============================================================================

INSERT INTO materials (name, material_type, specification, grade, standard, category, unit, density_kg_m3) VALUES
    ('Лист г/к',            'sheet',   '10*1500*6000',  'Ст3',   'ГОСТ 380-2005 / ГОСТ 19903-74', 'metal',    'кг',  7850),
    ('Круг',                'bar',     '16',            'Ст.20', 'ГОСТ 1050-88',                  'metal',    'кг',  7850),
    ('Резиновая смесь',     'rubber',  '7-В-14',        NULL,    'ГОСТ Р 54554-2011',             'rubber',   'кг',  1200),
    ('Проволока сварочная', 'wire',    '1.2 мм',        NULL,    NULL,                            'welding',  'кг',  7850),
    ('Лента упаковочная',   NULL,      '0.7x20 х/к',   NULL,    NULL,                            'packaging','кг',  NULL),
    ('Замок стальной',      NULL,      '19x45 б/п',    NULL,    NULL,                            'packaging','шт',  NULL);

-- =============================================================================
-- ИТОГОВАЯ СТРУКТУРА: 27 таблиц, 5 views, 16 триггеров, 93 индекса
-- =============================================================================
