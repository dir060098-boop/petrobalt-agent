import type { FieldStatus } from '../../types/mk'

const CONFIG: Record<FieldStatus, { label: string; cls: string }> = {
  extracted:      { label: 'Извлечено',    cls: 'bg-green-100 text-green-800' },
  confirmed:      { label: 'Подтверждено', cls: 'bg-blue-100 text-blue-800' },
  manual:         { label: 'Введено',      cls: 'bg-purple-100 text-purple-800' },
  calculated:     { label: 'Рассчитано',   cls: 'bg-cyan-100 text-cyan-800' },
  missing:        { label: 'Отсутствует',  cls: 'bg-red-100 text-red-800' },
  rejected:       { label: 'Отклонено',    cls: 'bg-orange-100 text-orange-800' },
  not_applicable: { label: 'Н/П',          cls: 'bg-gray-100 text-gray-500' },
}

export function StatusBadge({ status }: { status: FieldStatus }) {
  const { label, cls } = CONFIG[status] ?? CONFIG.missing
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${cls}`}>
      {label}
    </span>
  )
}

export function SeverityBadge({ severity }: { severity: 'critical' | 'warning' | 'info' }) {
  const map = {
    critical: 'bg-red-100 text-red-700',
    warning:  'bg-yellow-100 text-yellow-700',
    info:     'bg-blue-100 text-blue-700',
  }
  const labels = { critical: 'Критично', warning: 'Внимание', info: 'Инфо' }
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${map[severity]}`}>
      {labels[severity]}
    </span>
  )
}

export function RecommendBadge({ rec }: { rec: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    recommended:     { label: '★ Рекомендован', cls: 'bg-green-100 text-green-800' },
    alternative:     { label: 'Альтернатива',   cls: 'bg-yellow-100 text-yellow-800' },
    not_recommended: { label: 'Не рекомендован', cls: 'bg-red-100 text-red-700' },
  }
  const { label, cls } = map[rec] ?? map.not_recommended
  return <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${cls}`}>{label}</span>
}
