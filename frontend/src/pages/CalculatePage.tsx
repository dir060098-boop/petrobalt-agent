import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { calculateMK } from '../api/client'
import { usePipeline } from '../store/pipeline'
import { LoadingOverlay } from '../components/ui/Spinner'
import { Alert } from '../components/ui/Alert'
import type { MaterialInput } from '../types/mk'

export function CalculatePage() {
  const navigate = useNavigate()
  const { parseResult, validatorResult, setCalc, calcResult } = usePipeline()

  // Строим начальный список материалов из парсера
  const initMaterials = (): MaterialInput[] =>
    (parseResult?.planned_materials ?? []).map(m => ({
      name:         String(m.name.value ?? ''),
      unit:         String(m.unit.value ?? 'кг'),
      qty_per_unit: Number(m.qty_per_unit.value ?? 0),
      qty_issued:   m.qty_issued ? Number(m.qty_issued.value) : null,
      unit_price:   null,
      qty_in_stock: null,
      waste_factor: null,
    }))

  const [materials, setMaterials] = useState<MaterialInput[]>(initMaterials)
  // Флаг: поля, заполненные автоматически из БД, имеют значение != null из init
  // (фронтенд не знает заранее — просто подсветим непустые поля подсказкой)

  const mutation = useMutation({
    mutationFn: calculateMK,
    onSuccess: (data) => { setCalc(data) },
  })

  if (!parseResult) { navigate('/'); return null }

  const qty = Number(
    validatorResult?.validated_fields?.quantity?.value
    ?? parseResult.quantity.value
    ?? 1
  )
  const mkNumber    = String(parseResult.mk_number.value ?? '')
  const article     = String(parseResult.article.value ?? '')
  const productName = String(parseResult.product_name.value ?? '')

  function updateMat(i: number, field: keyof MaterialInput, val: string) {
    setMaterials(prev => prev.map((m, idx) =>
      idx !== i ? m : {
        ...m,
        [field]: ['unit','name'].includes(field) ? val : (val === '' ? null : Number(val)),
      }
    ))
  }

  function handleCalc() {
    mutation.mutate({
      mk_number: mkNumber,
      article,
      product_name: productName,
      quantity: qty,
      materials,
      route_card_id: parseResult?.route_card_id ?? null,
    })
  }

  const result = calcResult ?? mutation.data
  if (mutation.isPending) return <LoadingOverlay text="Рассчитываем BOM..." />

  return (
    <div className="max-w-5xl mx-auto py-10 px-4 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold">Расчёт BOM</h2>
          <p className="text-gray-500 text-sm">{productName} · МК {mkNumber} · {qty} шт.</p>
        </div>
        <button onClick={() => navigate('/validate')} className="btn-secondary text-sm">← Назад</button>
      </div>

      {/* Таблица ввода */}
      <div className="card overflow-x-auto">
        <h3 className="font-semibold text-gray-700 mb-4">Материалы — введите цены и остатки склада</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-500 border-b border-gray-100">
              <th className="pb-2 font-medium">Наименование</th>
              <th className="pb-2 font-medium">Ед.</th>
              <th className="pb-2 font-medium text-right">На 1 ед.</th>
              <th className="pb-2 font-medium text-right">Цена, руб.</th>
              <th className="pb-2 font-medium text-right">Склад</th>
              <th className="pb-2 font-medium text-right">К-т отхода</th>
            </tr>
          </thead>
          <tbody>
            {materials.map((m, i) => (
              <tr key={i} className="border-b border-gray-50">
                <td className="py-2 pr-3 font-medium text-gray-800">{m.name}</td>
                <td className="py-2 pr-3 text-gray-500">{m.unit}</td>
                <td className="py-2 pr-3 text-right text-gray-700">{m.qty_per_unit}</td>
                <td className="py-2 pr-2">
                  <input type="number" min="0" step="0.01"
                    placeholder="85.00"
                    value={m.unit_price ?? ''}
                    onChange={e => updateMat(i, 'unit_price', e.target.value)}
                    className="input text-right w-28"
                  />
                </td>
                <td className="py-2 pr-2">
                  <input type="number" min="0" step="0.01"
                    placeholder="0"
                    value={m.qty_in_stock ?? ''}
                    onChange={e => updateMat(i, 'qty_in_stock', e.target.value)}
                    className="input text-right w-24"
                  />
                </td>
                <td className="py-2">
                  <input type="number" min="1" step="0.01"
                    placeholder="авто"
                    value={m.waste_factor ?? ''}
                    onChange={e => updateMat(i, 'waste_factor', e.target.value)}
                    className="input text-right w-24"
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="flex items-center justify-between mt-5">
          <button onClick={handleCalc} className="btn-primary">
            Рассчитать →
          </button>
          <p className="text-xs text-gray-400">
            Цены и остатки склада подтягиваются из БД автоматически,
            если не заданы вручную.
          </p>
        </div>
      </div>

      {/* Результат */}
      {result && (
        <>
          {result.warnings.length > 0 && (
            <Alert type="warning" title="Предупреждения">
              <ul className="list-disc pl-4 space-y-1">
                {result.warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            </Alert>
          )}
          <div className="card overflow-x-auto">
            <h3 className="font-semibold text-gray-700 mb-4">Результат расчёта</h3>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-gray-500 border-b border-gray-100">
                  <th className="pb-2 font-medium">Материал</th>
                  <th className="pb-2 font-medium text-right">Требуется</th>
                  <th className="pb-2 font-medium text-right">К-т</th>
                  <th className="pb-2 font-medium text-right">Склад</th>
                  <th className="pb-2 font-medium text-right">Закупить</th>
                  <th className="pb-2 font-medium text-right">Цена</th>
                  <th className="pb-2 font-medium text-right">Стоимость</th>
                </tr>
              </thead>
              <tbody>
                {result.materials.map((m, i) => (
                  <tr key={i} className={`border-b border-gray-50 ${m.qty_to_purchase > 0 ? 'bg-yellow-50' : ''}`}>
                    <td className="py-2 pr-3 font-medium">{m.name}</td>
                    <td className="py-2 pr-3 text-right">{m.qty_required} {m.unit}</td>
                    <td className="py-2 pr-3 text-right text-gray-500">{m.waste_factor}×</td>
                    <td className="py-2 pr-3 text-right">{m.qty_in_stock}</td>
                    <td className={`py-2 pr-3 text-right font-medium ${m.qty_to_purchase > 0 ? 'text-orange-600' : 'text-green-600'}`}>
                      {m.qty_to_purchase > 0 ? `${m.qty_to_purchase} ${m.unit}` : '✓ Есть'}
                    </td>
                    <td className="py-2 pr-3 text-right text-gray-500">
                      {m.unit_price ? `${m.unit_price} руб.` : '—'}
                    </td>
                    <td className="py-2 text-right font-medium">
                      {m.cost ? `${m.cost.toLocaleString('ru')} ₽` : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-gray-200 font-semibold">
                  <td colSpan={6} className="pt-3 text-right text-gray-700">Итого себестоимость:</td>
                  <td className="pt-3 text-right text-gray-900">
                    {result.total_cost ? `${result.total_cost.toLocaleString('ru')} ₽` : 'Нет цен'}
                  </td>
                </tr>
              </tfoot>
            </table>
            <p className="text-xs text-gray-400 mt-3">Snapshot: {result.snapshot_at}</p>
          </div>

          <div className="flex gap-3">
            {result.needs_purchase && (
              <button onClick={() => navigate('/procure')} className="btn-primary">
                Найти поставщиков →
              </button>
            )}
            {!result.needs_purchase && (
              <Alert type="success">Склад покрывает всю потребность — закупка не требуется.</Alert>
            )}
          </div>
        </>
      )}
    </div>
  )
}
