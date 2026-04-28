// ── Общие ────────────────────────────────────────────────────────────────────

export type FieldStatus =
  | 'extracted'
  | 'missing'
  | 'calculated'
  | 'manual'
  | 'confirmed'
  | 'rejected'
  | 'not_applicable'

export interface FieldOut {
  value: string | number | null
  status: FieldStatus
  source: string
}

// ── Парсинг МК ───────────────────────────────────────────────────────────────

export interface MaterialOut {
  position: number | null
  name: FieldOut
  unit: FieldOut
  qty_issued?: FieldOut
  qty_per_unit: FieldOut
  qty_total: FieldOut
}

export interface ActualMaterialOut {
  position: number | null
  name: FieldOut
  unit: FieldOut
  qty_per_unit: FieldOut
  qty_total: FieldOut
  qty_remainder: FieldOut
  qty_returned: FieldOut
  qty_recycled: FieldOut
}

export interface OperationOut {
  sequence: number | null
  operation_name: FieldOut
  instruction_no: FieldOut
  department: FieldOut
  tech_description: FieldOut
  comments: FieldOut
}

export interface MKParseResponse {
  success: boolean
  confidence: number
  total_pages: number
  parse_errors: string[]
  missing_critical_fields: string[]
  route_card_id?: string | null   // UUID в БД (если подключена)
  file_url?: string | null        // URL в Supabase Storage

  mk_number: FieldOut
  article: FieldOut
  product_name: FieldOut
  quantity: FieldOut
  quantity_unit: FieldOut
  date_start: FieldOut
  date_end: FieldOut
  created_by: FieldOut
  verified_by: FieldOut

  planned_materials: MaterialOut[]
  actual_materials: ActualMaterialOut[]
  operations: OperationOut[]

  mass_before_trim_kg: FieldOut
  mass_after_trim_kg: FieldOut
}

// ── Валидация ────────────────────────────────────────────────────────────────

export type IssueSeverity = 'critical' | 'warning' | 'info'

export interface ValidationIssue {
  field: string
  severity: IssueSeverity
  message: string
  suggestion?: string
}

export interface FieldConfirmation {
  field_name: string
  value: string | number
}

export interface ValidatedField {
  value: string | number | null
  status: FieldStatus
  source: string
}

export interface ValidatorRequest {
  mk_number?: string | null
  article?: string | null
  product_name?: string | null
  quantity?: number | null
  quantity_unit?: string | null
  date_start?: string | null
  date_end?: string | null
  created_by?: string | null
  verified_by?: string | null
  field_statuses: Record<string, string>
  planned_materials_count: number
  actual_materials_count: number
  operations_count: number
  parse_errors: string[]
  confidence: number
  confirmations: FieldConfirmation[]
}

export interface ValidatorResponse {
  ready_for_calculation: boolean
  status: 'ready' | 'needs_input' | 'rejected'
  validated_fields: Record<string, ValidatedField>
  issues: ValidationIssue[]
  agent_summary: string
  blocked_reason?: string
  missing_critical: string[]
}

// ── Расчёт ───────────────────────────────────────────────────────────────────

export interface MaterialInput {
  name: string
  unit: string
  qty_per_unit: number
  qty_issued?: number | null
  unit_price?: number | null
  qty_in_stock?: number | null
  waste_factor?: number | null
}

export interface CalculatorRequest {
  mk_number: string
  article: string
  product_name: string
  quantity: number
  materials: MaterialInput[]
  default_waste_factor?: number | null
  route_card_id?: string | null  // передаём из parseResult для линковки purchase_request
}

export interface MaterialResult {
  name: string
  unit: string
  qty_per_unit: number
  waste_factor: number
  waste_factor_source: string
  qty_required: number
  qty_issued?: number | null
  unit_price?: number | null
  cost?: number | null
  qty_in_stock: number
  qty_to_purchase: number
}

export interface CalculatorResponse {
  mk_number: string
  article: string
  product_name: string
  quantity: number
  materials: MaterialResult[]
  total_cost?: number | null
  total_qty_to_purchase: number
  has_prices: boolean
  needs_purchase: boolean
  snapshot_at: string
  agent_summary: string
  warnings: string[]
}

// ── Закупка ──────────────────────────────────────────────────────────────────

export interface ProcurementMaterial {
  name: string
  unit: string
  qty_to_purchase: number
  unit_price_target?: number | null
  gost?: string | null
  comment?: string | null
}

export interface ProcurementRequest {
  mk_number: string
  article: string
  product_name: string
  materials: ProcurementMaterial[]
  region: string
  company_name: string
  contact_person: string
}

export interface SupplierCandidate {
  name: string
  contact?: string | null
  region?: string | null
  url?: string | null
  source: 'db' | 'web'
  materials_supplied: string[]
  notes?: string | null
}

export interface RFQItem {
  material_name: string
  unit: string
  quantity: number
  target_price?: number | null
  gost?: string | null
}

export interface RFQLetter {
  supplier_name: string
  supplier_contact?: string | null
  subject: string
  body: string
  items: RFQItem[]
}

export interface ProcurementResponse {
  mk_number: string
  product_name: string
  region: string
  materials_to_purchase: ProcurementMaterial[]
  supplier_candidates: SupplierCandidate[]
  rfq_letters: RFQLetter[]
  agent_summary: string
  warnings: string[]
}

// ── Сравнение КП ─────────────────────────────────────────────────────────────

export interface QuoteItem {
  material_name: string
  unit: string
  quantity_requested: number
  unit_price: number
  currency: string
}

export interface SupplierQuote {
  supplier_name: string
  supplier_type: 'manufacturer' | 'distributor' | 'trader' | 'unknown'
  is_verified: boolean
  has_vat: boolean
  lead_time_days: number
  contact?: string | null
  notes?: string | null
  items: QuoteItem[]
}

export interface CompareRequest {
  mk_number: string
  material_name: string
  quantity_required: number
  quotes: SupplierQuote[]
  weight_price?: number
  weight_lead_time?: number
  weight_verification?: number
  weight_vat?: number
  weight_type?: number
}

export interface ScoreBreakdown {
  price: number
  lead_time: number
  verification: number
  vat: number
  supplier_type: number
  total: number
}

export interface ScoredQuote {
  rank: number
  supplier_name: string
  supplier_type: string
  is_verified: boolean
  has_vat: boolean
  lead_time_days: number
  unit_price: number
  total_price: number
  scores: ScoreBreakdown
  recommendation: 'recommended' | 'alternative' | 'not_recommended'
}

export interface CompareResult {
  material_name: string
  quantity_required: number
  quotes_count: number
  scored_quotes: ScoredQuote[]
  winner?: string | null
  price_spread_pct: number
  weights_used: Record<string, number>
  summary: string
}

export interface CompareBatchResponse {
  mk_number: string
  results: CompareResult[]
  overall_summary: string
  warnings: string[]
}
