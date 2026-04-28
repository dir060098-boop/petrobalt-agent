import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { procureMK } from '../api/client'
import { usePipeline } from '../store/pipeline'
import { LoadingOverlay } from '../components/ui/Spinner'
import { Alert } from '../components/ui/Alert'

export function ProcurePage() {
  const navigate = useNavigate()
  const { parseResult, calcResult, setProcure, procureResult } = usePipeline()
  const [region,  setRegion]  = useState('Калининград')
  const [contact, setContact] = useState('')

  const mutation = useMutation({
    mutationFn: procureMK,
    onSuccess: (data) => { setProcure(data) },
  })

  if (!calcResult) { navigate('/calculate'); return null }

  const materialsToOrder = calcResult.materials
    .filter(m => m.qty_to_purchase > 0)
    .map(m => ({
      name: m.name, unit: m.unit,
      qty_to_purchase: m.qty_to_purchase,
      unit_price_target: m.unit_price ?? null,
    }))

  function handleProcure() {
    mutation.mutate({
      mk_number:    calcResult!.mk_number,
      article:      calcResult!.article,
      product_name: calcResult!.product_name,
      materials:    materialsToOrder,
      region,
      company_name: 'ООО "Петробалт Сервис"',
      contact_person: contact,
    })
  }

  const result = procureResult ?? mutation.data
  if (mutation.isPending) return <LoadingOverlay text="Ищем поставщиков..." />

  return (
    <div className="max-w-4xl mx-auto py-10 px-4 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold">Поиск поставщиков</h2>
          <p className="text-gray-500 text-sm">Материалов к закупке: {materialsToOrder.length}</p>
        </div>
        <button onClick={() => navigate('/calculate')} className="btn-secondary text-sm">← Назад</button>
      </div>

      {/* Что закупаем */}
      <div className="card">
        <h3 className="font-semibold text-gray-700 mb-3">Список к закупке</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-500 border-b border-gray-100">
              <th className="pb-2 font-medium">Материал</th>
              <th className="pb-2 font-medium text-right">Количество</th>
              <th className="pb-2 font-medium text-right">Ориент. цена</th>
            </tr>
          </thead>
          <tbody>
            {materialsToOrder.map((m, i) => (
              <tr key={i} className="border-b border-gray-50">
                <td className="py-2 font-medium">{m.name}</td>
                <td className="py-2 text-right">{m.qty_to_purchase} {m.unit}</td>
                <td className="py-2 text-right text-gray-500">
                  {m.unit_price_target ? `${m.unit_price_target} руб.` : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Параметры запроса */}
      {!result && (
        <div className="card space-y-4">
          <h3 className="font-semibold text-gray-700">Параметры</h3>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm text-gray-600 mb-1">Регион поиска</label>
              <input className="input" value={region} onChange={e => setRegion(e.target.value)} />
            </div>
            <div>
              <label className="block text-sm text-gray-600 mb-1">Контактное лицо</label>
              <input className="input" placeholder="Иванов И.И." value={contact} onChange={e => setContact(e.target.value)} />
            </div>
          </div>
          <button onClick={handleProcure} className="btn-primary">
            Найти поставщиков и сформировать RFQ →
          </button>
        </div>
      )}

      {/* Результат */}
      {result && (
        <>
          <Alert type={result.supplier_candidates.length > 0 ? 'success' : 'info'}
                 title="Результат поиска">
            {result.agent_summary}
          </Alert>

          {result.warnings.length > 0 && (
            <Alert type="warning">
              {result.warnings.map((w, i) => <p key={i}>{w}</p>)}
            </Alert>
          )}

          {/* Поставщики */}
          {result.supplier_candidates.length > 0 && (
            <div className="card">
              <h3 className="font-semibold text-gray-700 mb-3">Найденные поставщики</h3>
              <div className="space-y-3">
                {result.supplier_candidates.map((s, i) => (
                  <div key={i} className="border border-gray-100 rounded-lg p-3">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{s.name}</span>
                      <span className="text-xs text-gray-400">{s.source === 'db' ? '✓ В базе' : '🌐 Веб'}</span>
                      {s.region && <span className="text-xs text-gray-400">· {s.region}</span>}
                    </div>
                    {s.contact && <p className="text-sm text-gray-500 mt-1">{s.contact}</p>}
                    {s.url && <a href={s.url} target="_blank" rel="noopener noreferrer" className="text-xs text-brand-600 hover:underline">{s.url}</a>}
                    <p className="text-xs text-gray-400 mt-1">Материалы: {s.materials_supplied.join(', ')}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* RFQ письма */}
          {result.rfq_letters.length > 0 && (
            <div className="card space-y-4">
              <h3 className="font-semibold text-gray-700">RFQ-письма</h3>
              {result.rfq_letters.map((rfq, i) => (
                <div key={i} className="border border-gray-200 rounded-lg overflow-hidden">
                  <div className="bg-gray-50 px-4 py-2 flex items-center justify-between">
                    <span className="font-medium text-sm">{rfq.supplier_name}</span>
                    <span className="text-xs text-gray-500">{rfq.subject}</span>
                  </div>
                  <pre className="p-4 text-xs text-gray-700 whitespace-pre-wrap font-sans leading-relaxed max-h-60 overflow-y-auto">
                    {rfq.body}
                  </pre>
                  <div className="px-4 pb-3">
                    <button
                      onClick={() => navigator.clipboard.writeText(rfq.body)}
                      className="btn-secondary text-xs"
                    >
                      Копировать письмо
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="flex gap-3">
            <button onClick={() => navigate('/compare')} className="btn-primary">
              Сравнить КП →
            </button>
            <button onClick={() => { setProcure(null as never); mutation.reset() }} className="btn-secondary">
              Повторить поиск
            </button>
          </div>
        </>
      )}
    </div>
  )
}
