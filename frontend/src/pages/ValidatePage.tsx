import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { validateMK } from '../api/client'
import { usePipeline } from '../store/pipeline'
import { FieldRow } from '../components/FieldRow'
import { StatusBadge, SeverityBadge } from '../components/ui/Badge'
import { LoadingOverlay } from '../components/ui/Spinner'
import { Alert } from '../components/ui/Alert'
import type { FieldConfirmation, MKParseResponse, FieldOut } from '../types/mk'

function parseToRequest(parsed: MKParseResponse, confirmations: FieldConfirmation[]) {
  const statuses: Record<string, string> = {}
  const fields = ['mk_number','article','product_name','quantity','quantity_unit',
                  'date_start','date_end','created_by','verified_by'] as const
  for (const f of fields) {
    statuses[f] = (parsed[f] as FieldOut).status
  }
  return {
    mk_number:    (parsed.mk_number.value as string) ?? undefined,
    article:      (parsed.article.value as string) ?? undefined,
    product_name: (parsed.product_name.value as string) ?? undefined,
    quantity:     (parsed.quantity.value as number) ?? undefined,
    quantity_unit:(parsed.quantity_unit.value as string) ?? undefined,
    date_start:   (parsed.date_start.value as string) ?? undefined,
    date_end:     (parsed.date_end.value as string) ?? undefined,
    created_by:   (parsed.created_by.value as string) ?? undefined,
    verified_by:  (parsed.verified_by.value as string) ?? undefined,
    field_statuses: statuses,
    planned_materials_count: parsed.planned_materials.length,
    actual_materials_count:  parsed.actual_materials.length,
    operations_count:        parsed.operations.length,
    parse_errors:  parsed.parse_errors,
    confidence:    parsed.confidence,
    confirmations,
  }
}

export function ValidatePage() {
  const navigate = useNavigate()
  const { parseResult, setValidate } = usePipeline()
  const [confirmations, setConfirmations] = useState<FieldConfirmation[]>([])

  const mutation = useMutation({
    mutationFn: validateMK,
    onSuccess: (data) => {
      setValidate(data)
      if (data.ready_for_calculation) navigate('/calculate')
    },
  })

  if (!parseResult) {
    navigate('/')
    return null
  }

  function handleConfirm(conf: FieldConfirmation) {
    setConfirmations(prev => {
      const next = prev.filter(c => c.field_name !== conf.field_name)
      return [...next, conf]
    })
  }

  function getField(name: string): FieldOut {
    const p = parseResult!
    const map: Record<string, FieldOut> = {
      mk_number: p.mk_number, article: p.article, product_name: p.product_name,
      quantity: p.quantity, quantity_unit: p.quantity_unit,
      date_start: p.date_start, date_end: p.date_end,
      created_by: p.created_by, verified_by: p.verified_by,
    }
    const conf = confirmations.find(c => c.field_name === name)
    if (conf) return { value: conf.value, status: map[name].status === 'missing' ? 'manual' : 'confirmed', source: 'user' }
    return map[name] ?? { value: null, status: 'missing', source: 'mk' }
  }

  const res = mutation.data
  if (mutation.isPending) return <LoadingOverlay text="Проверяем МК агентом..." />

  return (
    <div className="max-w-3xl mx-auto py-10 px-4 space-y-6">
      <div>
        <h2 className="text-xl font-bold">Проверка МК</h2>
        <p className="text-gray-500 text-sm mt-1">
          Confidence: <b>{(parseResult.confidence * 100).toFixed(0)}%</b> · Страниц: {parseResult.total_pages}
        </p>
      </div>

      {/* Поля заголовка */}
      <div className="card">
        <h3 className="font-semibold text-gray-700 mb-4">Заголовок МК</h3>
        {[
          ['mk_number',    'Номер МК'],
          ['article',      'Артикул'],
          ['product_name', 'Наименование'],
          ['quantity',     'Количество'],
          ['quantity_unit','Ед. изм.'],
          ['date_start',   'Дата составления'],
          ['date_end',     'Дата окончания'],
          ['created_by',   'Составил'],
          ['verified_by',  'Проверил'],
        ].map(([name, label]) => (
          <FieldRow
            key={name}
            label={label}
            fieldName={name}
            field={getField(name)}
            onConfirm={handleConfirm}
          />
        ))}
      </div>

      {/* Материалы */}
      <div className="card">
        <h3 className="font-semibold text-gray-700 mb-3">Плановые материалы</h3>
        {parseResult.planned_materials.length === 0 ? (
          <p className="text-sm text-gray-400 italic">Не найдены</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500 border-b border-gray-100">
                <th className="pb-2 font-medium">№</th>
                <th className="pb-2 font-medium">Наименование</th>
                <th className="pb-2 font-medium">Ед.</th>
                <th className="pb-2 font-medium text-right">На 1 ед.</th>
                <th className="pb-2 font-medium text-right">Итого</th>
                <th className="pb-2 font-medium">Статус</th>
              </tr>
            </thead>
            <tbody>
              {parseResult.planned_materials.map((m, i) => (
                <tr key={i} className="border-b border-gray-50">
                  <td className="py-2 text-gray-400">{m.position ?? i + 1}</td>
                  <td className="py-2">{m.name.value}</td>
                  <td className="py-2 text-gray-500">{m.unit.value}</td>
                  <td className="py-2 text-right">{m.qty_per_unit.value}</td>
                  <td className="py-2 text-right">{m.qty_total.value}</td>
                  <td className="py-2"><StatusBadge status={m.name.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Результат валидации */}
      {res && (
        <div className="space-y-3">
          <Alert type={res.ready_for_calculation ? 'success' : 'warning'}
                 title={res.ready_for_calculation ? 'МК готова к расчёту' : 'Требуется доработка'}>
            {res.agent_summary}
          </Alert>
          {res.issues.length > 0 && (
            <div className="card space-y-2">
              <h3 className="font-semibold text-gray-700">Замечания агента</h3>
              {res.issues.map((issue, i) => (
                <div key={i} className="flex gap-3 items-start text-sm">
                  <SeverityBadge severity={issue.severity} />
                  <div>
                    <span className="text-gray-800">{issue.message}</span>
                    {issue.suggestion && (
                      <p className="text-gray-400 text-xs mt-0.5">{issue.suggestion}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Кнопки */}
      <div className="flex gap-3">
        <button onClick={() => navigate('/')} className="btn-secondary">← Загрузить другой файл</button>
        <button
          onClick={() => mutation.mutate(parseToRequest(parseResult, confirmations))}
          className="btn-primary"
        >
          Проверить агентом
        </button>
        {res?.ready_for_calculation && (
          <button onClick={() => navigate('/calculate')} className="btn-primary">
            Перейти к расчёту →
          </button>
        )}
      </div>
    </div>
  )
}
