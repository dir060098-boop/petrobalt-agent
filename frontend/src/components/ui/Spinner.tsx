export function Spinner({ size = 'md' }: { size?: 'sm' | 'md' | 'lg' }) {
  const sz = { sm: 'h-4 w-4', md: 'h-8 w-8', lg: 'h-12 w-12' }[size]
  return (
    <div className={`${sz} animate-spin rounded-full border-2 border-gray-200 border-t-brand-600`} />
  )
}

export function LoadingOverlay({ text = 'Загрузка...' }: { text?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16">
      <Spinner size="lg" />
      <p className="text-gray-500 text-sm">{text}</p>
    </div>
  )
}
