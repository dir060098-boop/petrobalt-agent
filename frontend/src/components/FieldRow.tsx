import { useState } from 'react'
import { StatusBadge } from './ui/Badge'
import type { FieldOut, FieldConfirmation } from '../types/mk'

interface Props {
  label: string
  field: FieldOut
  fieldName: string
  editable?: boolean
  onConfirm?: (conf: FieldConfirmation) => void
}

export function FieldRow({ label, field, fieldName, editable = true, onConfirm }: Props) {
  const [editing, setEditing]   = useState(false)
  const [draft,   setDraft]     = useState(String(field.value ?? ''))
  const isMissing = field.status === 'missing'

  function handleSave() {
    onConfirm?.({ field_name: fieldName, value: draft })
    setEditing(false)
  }

  return (
    <div className={`flex items-center gap-3 py-2.5 border-b border-gray-100 last:border-0
                    ${isMissing ? 'bg-red-50 -mx-6 px-6' : ''}`}>
      {/* Метка */}
      <span className="w-44 shrink-0 text-sm text-gray-600 font-medium">{label}</span>

      {/* Значение */}
      <div className="flex-1">
        {editing ? (
          <div className="flex gap-2">
            <input
              autoFocus
              className="input text-sm"
              value={draft}
              onChange={e => setDraft(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleSave(); if (e.key === 'Escape') setEditing(false) }}
            />
            <button onClick={handleSave}  className="btn-primary text-xs px-3 py-1.5">Сохранить</button>
            <button onClick={() => setEditing(false)} className="btn-secondary text-xs px-3 py-1.5">Отмена</button>
          </div>
        ) : (
          <span className={`text-sm ${isMissing ? 'text-red-500 italic' : 'text-gray-900'}`}>
            {field.value != null ? String(field.value) : '— не заполнено —'}
          </span>
        )}
      </div>

      {/* Статус */}
      <StatusBadge status={field.status} />

      {/* Кнопка редактирования */}
      {editable && !editing && (
        <button
          onClick={() => setEditing(true)}
          className="text-xs text-brand-600 hover:text-brand-800 shrink-0"
        >
          {isMissing ? '+ Ввести' : 'Изменить'}
        </button>
      )}
    </div>
  )
}
