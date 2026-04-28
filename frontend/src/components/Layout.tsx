import { Link, useLocation } from 'react-router-dom'

const STEPS = [
  { path: '/',         label: '1. Загрузка' },
  { path: '/validate', label: '2. Проверка' },
  { path: '/calculate',label: '3. Расчёт' },
  { path: '/procure',  label: '4. Закупка' },
  { path: '/compare',  label: '5. Сравнение' },
]

export function Layout({ children }: { children: React.ReactNode }) {
  const { pathname } = useLocation()

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-6 py-3">
        <div className="max-w-5xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-lg font-bold text-brand-700">Петробалт</span>
            <span className="text-gray-300">|</span>
            <span className="text-sm text-gray-500">Расчёт материалов</span>
          </div>
        </div>
      </header>

      {/* Stepper */}
      <nav className="bg-gray-50 border-b border-gray-200 px-6 py-2">
        <div className="max-w-5xl mx-auto flex gap-1">
          {STEPS.map((step, i) => {
            const active = pathname === step.path
            return (
              <Link
                key={step.path}
                to={step.path}
                className={`px-3 py-1.5 rounded text-xs font-medium transition-colors
                  ${active
                    ? 'bg-brand-600 text-white'
                    : 'text-gray-500 hover:text-gray-800 hover:bg-gray-100'}`}
              >
                {step.label}
              </Link>
            )
          })}
        </div>
      </nav>

      {/* Main */}
      <main className="flex-1">
        {children}
      </main>

      {/* Footer */}
      <footer className="border-t border-gray-200 py-3 px-6 text-center text-xs text-gray-400">
        ООО «Петробалт Сервис» · AI-агент расчёта материалов
      </footer>
    </div>
  )
}
