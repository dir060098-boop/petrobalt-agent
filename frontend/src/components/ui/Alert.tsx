interface AlertProps {
  type: 'error' | 'warning' | 'success' | 'info'
  title?: string
  children: React.ReactNode
}

export function Alert({ type, title, children }: AlertProps) {
  const styles = {
    error:   { wrap: 'bg-red-50 border-red-200 text-red-800',    icon: '✕' },
    warning: { wrap: 'bg-yellow-50 border-yellow-200 text-yellow-800', icon: '⚠' },
    success: { wrap: 'bg-green-50 border-green-200 text-green-800',  icon: '✓' },
    info:    { wrap: 'bg-blue-50 border-blue-200 text-blue-800',   icon: 'ℹ' },
  }[type]

  return (
    <div className={`border rounded-lg p-4 ${styles.wrap}`}>
      {title && (
        <div className="flex items-center gap-2 font-semibold mb-1">
          <span>{styles.icon}</span>
          {title}
        </div>
      )}
      <div className="text-sm">{children}</div>
    </div>
  )
}
