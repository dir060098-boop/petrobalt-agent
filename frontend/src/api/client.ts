import axios from 'axios'
import type {
  MKParseResponse,
  ValidatorRequest,
  ValidatorResponse,
  CalculatorRequest,
  CalculatorResponse,
  ProcurementRequest,
  ProcurementResponse,
  CompareBatchResponse,
} from '../types/mk'

const api = axios.create({
  baseURL: '/api',
  timeout: 60_000,
})

// ── МК ───────────────────────────────────────────────────────────────────────

export async function parseMK(file: File): Promise<MKParseResponse> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post<MKParseResponse>('/mk/parse', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function validateMK(req: ValidatorRequest): Promise<ValidatorResponse> {
  const { data } = await api.post<ValidatorResponse>('/mk/validate', req)
  return data
}

export async function calculateMK(req: CalculatorRequest): Promise<CalculatorResponse> {
  const { data } = await api.post<CalculatorResponse>('/mk/calculate', req)
  return data
}

export async function procureMK(req: ProcurementRequest): Promise<ProcurementResponse> {
  const { data } = await api.post<ProcurementResponse>('/mk/procure', req)
  return data
}

export async function compareQuotes(req: {
  mk_number: string
  items: import('../types/mk').CompareRequest[]
}): Promise<CompareBatchResponse> {
  const { data } = await api.post<CompareBatchResponse>('/mk/compare', req)
  return data
}
