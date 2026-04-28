/**
 * Хранит состояние всего pipeline в памяти (без БД для MVP).
 * Пробрасывается через React context.
 */
import React, { createContext, useContext, useState } from 'react'
import type {
  MKParseResponse,
  ValidatorResponse,
  CalculatorResponse,
  ProcurementResponse,
  CompareBatchResponse,
} from '../types/mk'

interface PipelineState {
  parseResult:    MKParseResponse | null
  validatorResult: ValidatorResponse | null
  calcResult:     CalculatorResponse | null
  procureResult:  ProcurementResponse | null
  compareResult:  CompareBatchResponse | null

  setParse:    (v: MKParseResponse) => void
  setValidate: (v: ValidatorResponse) => void
  setCalc:     (v: CalculatorResponse) => void
  setProcure:  (v: ProcurementResponse) => void
  setCompare:  (v: CompareBatchResponse) => void
  reset:       () => void
}

const PipelineCtx = createContext<PipelineState | null>(null)

export function PipelineProvider({ children }: { children: React.ReactNode }) {
  const [parseResult,    setParse]    = useState<MKParseResponse | null>(null)
  const [validatorResult, setValidate] = useState<ValidatorResponse | null>(null)
  const [calcResult,     setCalc]     = useState<CalculatorResponse | null>(null)
  const [procureResult,  setProcure]  = useState<ProcurementResponse | null>(null)
  const [compareResult,  setCompare]  = useState<CompareBatchResponse | null>(null)

  function reset() {
    setParse(null); setValidate(null); setCalc(null)
    setProcure(null); setCompare(null)
  }

  return (
    <PipelineCtx.Provider value={{
      parseResult, validatorResult, calcResult, procureResult, compareResult,
      setParse, setValidate, setCalc, setProcure, setCompare, reset,
    }}>
      {children}
    </PipelineCtx.Provider>
  )
}

export function usePipeline() {
  const ctx = useContext(PipelineCtx)
  if (!ctx) throw new Error('usePipeline must be used inside PipelineProvider')
  return ctx
}
