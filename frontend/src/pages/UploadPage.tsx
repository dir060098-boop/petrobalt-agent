import { useCallback, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { parseMK } from '../api/client'
import { usePipeline } from '../store/pipeline'
import { LoadingOverlay } from '../components/ui/Spinner'
import { Alert } from '../components/ui/Alert'

export function UploadPage() {
  const navigate  = useNavigate()
  const { setParse, reset } = usePipeline()
  const [dragging, setDragging] = useState(false)
  const [file,     setFile]     = useState<File | null>(null)
  const [error,    setError]    = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: parseMK,
    onSuccess: (data) => {
      setParse(data)
      navigate('/validate')
    },
    onError: (err: Error) => setError(err.message),
  })

  const handleFile = useCallback((f: File) => {
    if (!f.name.toLowerCase().endsWith('.pdf')) {
      setError('Ожидается PDF-файл')
      return
    }
    setFile(f)
    setError(null)
  }, [])

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const f = e.dataTransfer.files[0]
    if (f) handleFile(f)
  }, [handleFile])

  function onInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    if (f) handleFile(f)
  }

  function handleUpload() {
    if (!file) return
    reset()
    mutation.mutate(file)
  }

  if (mutation.isPending) return <LoadingOverlay text="Парсим МК..." />

  return (
    <div className="max-w-xl mx-auto py-16 px-4">
      {/* Заголовок */}
      <div className="text-center mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Расчёт материалов</h1>
        <p className="text-gray-500 mt-1">Загрузите PDF Маршрутной Карты для начала работы</p>
      </div>

      {/* Drop zone */}
      <div
        onDrop={onDrop}
        onDragOver={e => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        className={`border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-colors
          ${dragging ? 'border-brand-500 bg-brand-50' : 'border-gray-300 hover:border-brand-400 hover:bg-gray-50'}`}
      >
        <div className="text-4xl mb-3">📄</div>
        {file ? (
          <div>
            <p className="font-medium text-gray-800">{file.name}</p>
            <p className="text-sm text-gray-500 mt-1">{(file.size / 1024).toFixed(0)} КБ</p>
          </div>
        ) : (
          <div>
            <p className="text-gray-600 font-medium">Перетащите PDF сюда</p>
            <p className="text-gray-400 text-sm mt-1">или</p>
          </div>
        )}
        <label className="mt-4 inline-block btn-secondary cursor-pointer text-sm">
          Выбрать файл
          <input type="file" accept=".pdf" className="hidden" onChange={onInputChange} />
        </label>
      </div>

      {/* Ошибка */}
      {error && (
        <div className="mt-4">
          <Alert type="error">{error}</Alert>
        </div>
      )}

      {/* Кнопка */}
      <button
        onClick={handleUpload}
        disabled={!file || mutation.isPending}
        className="btn-primary w-full mt-6 justify-center"
      >
        Распарсить МК →
      </button>
    </div>
  )
}
