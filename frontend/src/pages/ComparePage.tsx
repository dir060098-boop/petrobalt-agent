import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { compareQuotes } from '../api/client'
import { usePipeline } from '../store/pipeline'
import { LoadingOverlay } from '../components/ui/Spinner'
import { Alert } from '../components/ui/Alert'
import { RecommendBadge } from '../components/ui/Badge'
import type { SupplierQuote, QuoteItem } from '../types/mk'

function emptyQuote(materialName: string, unit: string, qty: number): SupplierQuote {
  return {
    supplier_name: '',
    supplier_type: 'distributor',
    is_verified: false,
    has_vat: true,
    lead_time_days: 14,
    items: [{ material_name: materialName, unit, quantity_requested: qty, unit_price: 0, currency: 'RUB' }],
  }
}

export function ComparePage() {
  const navigate  = useNavigate()
  const { calcResult, setCompare, compareResult } = usePipeline()

  // Список материалов к сравнению
  const purchaseMats = (calcResult?.materials ?? []).filter(m => m.qty_to_purchase > 0)

  // Состояние: для каждого материала список quote-форм
  const [quoteForms, setQuoteForms] = useState<Record<string, SupplierQuote[]>>(
    () => Object.fromEntries(
      purchaseMats.map(m => [m.name, [
        emptyQuote(m.name, m.unit, m.qty_to_purchase),
        emptyQuote(m.name, m.unit, m.qty_to_purchase),
      ]])
    )
  )

  const mutation = useMutation({
    mutationFn: compareQuotes,
    onSuccess: (data) => { setCompare(data) },
  })

  if (!calcResult) { navigate('/calculate'); return null }
  if (mutation.isPending) return <LoadingOverlay text="Сравниваем предложения..." />

  function updateQuote(matName: string, qi: number, field: keyof SupplierQuote | 'unit_price', val: string | boolean | number) {
    setQuoteForms(prev => {
      const quotes = [...(prev[matName] ?? [])]
      if (field === 'unit_price') {
        const items: QuoteItem[] = [{ ...quotes[qi].items[0], unit_price: Number(val) }]
        quotes[qi] = { ...quotes[qi], items }
      } else {
        quotes[qi] = { ...quotes[qi], [field]: val }
      }
      return { ...prev, [matName]: quotes }
    })
  }

  function addQuote(matName: string, unit: string, qty: number) {
    setQuoteForms(prev => ({
      ...prev,
      [matName]: [...(prev[matName] ?? []), emptyQuote(matName, unit, qty)],
    }))
  }

  function removeQuote(matName: string, qi: number) {
    setQuoteForms(prev => ({
      ...prev,
      [matName]: (prev[matName] ?? []).filter((_, i) => i !== qi),
    }))
  }

  function handleCompare() {
    if (!calcResult) return
    const items = purchaseMats.map(m => ({
      mk_number: calcResult!.mk_number,
      material_name: m.name,
      quantity_required: m.qty_to_purchase,
      quotes: (quoteForms[m.name] ?? []).filter(q => q.supplier_name.trim() !== '' && q.items[0].unit_price > 0),
    })).filter(item => item.quotes.length > 0)

    if (items.length === 0) return

    mutation.mutate({ mk_number: calcResult!.mk_number, items })
  }

  const result = compareResult ?? mutation.data

  const scoreBar = (val: number) => (
    <div className="flex items-center gap-2">
      <div className="flex-1 bg-gray-100 rounded-full h-1.5">
        <div className="bg-brand-500 h-1.5 rounded-full" style={{ width: `${val * 100}%` }} />
      </div>
      <span className="text-xs text-gray-500 w-8 text-right">{(val * 100).toFixed(0)}%</span>
    </div>
  )

  return (
    <div className="max-w-5xl mx-auto py-10 px-4 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold">Сравнение КП</h2>
          <p className="text-gray-500 text-sm">Введите полученные коммерческие предложения</p>
        </div>
        <button onClick={() => navigate('/procure')} className="btn-secondary text-sm">← Назад</button>
      </div>

      {/* Форма ввода КП */}
      {!result && purchaseMats.map(m => (
        <div key={m.name} className="card space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold text-gray-800">{m.name}</h3>
            <span className="text-sm text-gray-500">Нужно: {m.qty_to_purchase} {m.unit}</span>
          </div>

          {(quoteForms[m.name] ?? []).map((q, qi) => (
            <div key={qi} className="border border-gray-100 rounded-lg p-4 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-gray-600">КП #{qi + 1}</span>
                <button onClick={() => removeQuote(m.name, qi)} className="text-xs text-red-400 hover:text-red-600">× Удалить</button>
              </div>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">Поставщик</label>
                  <input className="input text-sm" placeholder="ООО Металлоторг"
                    value={q.supplier_name}
                    onChange={e => updateQuote(m.name, qi, 'supplier_name', e.target.value)} />
                </div>
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">Цена, руб/ед.</label>
                  <input type="number" min="0" step="0.01" className="input text-sm"
                    value={q.items[0].unit_price || ''}
                    onChange={e => updateQuote(m.name, qi, 'unit_price', e.target.value)} />
                </div>
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">Срок, дн.</label>
                  <input type="number" min="1" className="input text-sm"
                    value={q.lead_time_days}
                    onChange={e => updateQuote(m.name, qi, 'lead_time_days', Number(e.target.value))} />
                </div>
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">Тип</label>
                  <select className="input text-sm"
                    value={q.supplier_type}
                    onChange={e => updateQuote(m.name, qi, 'supplier_type', e.target.value)}>
                    <option value="manufacturer">Производитель</option>
                    <option value="distributor">Дистрибьютор</option>
                    <option value="trader">Трейдер</option>
                    <option value="unknown">Неизвестно</option>
                  </select>
                </div>
              </div>
              <div className="flex gap-4 text-sm">
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input type="checkbox" checked={q.has_vat}
                    onChange={e => updateQuote(m.name, qi, 'has_vat', e.target.checked)} />
                  С НДС
                </label>
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input type="checkbox" checked={q.is_verified}
                    onChange={e => updateQuote(m.name, qi, 'is_verified', e.target.checked)} />
                  В базе поставщиков
                </label>
              </div>
            </div>
          ))}

          <button onClick={() => addQuote(m.name, m.unit, m.qty_to_purchase)}
            className="btn-secondary text-sm">+ Добавить КП</button>
        </div>
      ))}

      {!result && (
        <button onClick={handleCompare} className="btn-primary">Сравнить →</button>
      )}

      {/* Результаты */}
      {result && (
        <>
          <Alert type="success" title="Сравнение завершено">{result.overall_summary}</Alert>

          {result.warnings.length > 0 && (
            <Alert type="warning">
              {result.warnings.map((w, i) => <p key={i}>{w}</p>)}
            </Alert>
          )}

          {result.results.map((res, ri) => (
            <div key={ri} className="card space-y-4">
              <div>
                <h3 className="font-semibold text-gray-800">{res.material_name}</h3>
                <p className="text-xs text-gray-400">{res.summary}</p>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-gray-500 border-b border-gray-100">
                      <th className="pb-2 font-medium">Ранг</th>
                      <th className="pb-2 font-medium">Поставщик</th>
                      <th className="pb-2 font-medium text-right">Цена</th>
                      <th className="pb-2 font-medium text-right">Срок</th>
                      <th className="pb-2 font-medium w-48">Score</th>
                      <th className="pb-2 font-medium">Итог</th>
                      <th className="pb-2 font-medium">Рекомендация</th>
                    </tr>
                  </thead>
                  <tbody>
                    {res.scored_quotes.map((sq, i) => (
                      <tr key={i} className={`border-b border-gray-50 ${sq.rank === 1 ? 'bg-green-50' : ''}`}>
                        <td className="py-3 font-bold text-gray-700">#{sq.rank}</td>
                        <td className="py-3">
                          <div className="font-medium">{sq.supplier_name}</div>
                          <div className="text-xs text-gray-400 flex gap-2 mt-0.5">
                            <span>{sq.supplier_type}</span>
                            {sq.is_verified && <span>✓ верифицирован</span>}
                            {sq.has_vat ? <span>с НДС</span> : <span className="text-orange-500">без НДС</span>}
                          </div>
                        </td>
                        <td className="py-3 text-right font-medium">{sq.unit_price.toLocaleString('ru')} ₽</td>
                        <td className="py-3 text-right">{sq.lead_time_days} дн.</td>
                        <td className="py-3 w-48 pr-4">
                          <div className="space-y-1 text-xs text-gray-500">
                            <div className="flex gap-2 items-center"><span className="w-16">Цена</span>{scoreBar(sq.scores.price)}</div>
                            <div className="flex gap-2 items-center"><span className="w-16">Срок</span>{scoreBar(sq.scores.lead_time)}</div>
                            <div className="flex gap-2 items-center"><span className="w-16">Верификация</span>{scoreBar(sq.scores.verification)}</div>
                          </div>
                        </td>
                        <td className="py-3 font-bold text-brand-700">{(sq.scores.total * 100).toFixed(0)}%</td>
                        <td className="py-3"><RecommendBadge rec={sq.recommendation} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}

          <div className="flex gap-3">
            <button onClick={() => { setCompare(null as never); mutation.reset() }} className="btn-secondary">
              Пересчитать
            </button>
            <button onClick={() => navigate('/')} className="btn-primary">
              Новая МК
            </button>
          </div>
        </>
      )}
    </div>
  )
}
