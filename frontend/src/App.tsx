import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { PipelineProvider } from './store/pipeline'
import { Layout } from './components/Layout'
import { UploadPage }    from './pages/UploadPage'
import { ValidatePage }  from './pages/ValidatePage'
import { CalculatePage } from './pages/CalculatePage'
import { ProcurePage }   from './pages/ProcurePage'
import { ComparePage }   from './pages/ComparePage'

export default function App() {
  return (
    <BrowserRouter>
      <PipelineProvider>
        <Layout>
          <Routes>
            <Route path="/"          element={<UploadPage />} />
            <Route path="/validate"  element={<ValidatePage />} />
            <Route path="/calculate" element={<CalculatePage />} />
            <Route path="/procure"   element={<ProcurePage />} />
            <Route path="/compare"   element={<ComparePage />} />
          </Routes>
        </Layout>
      </PipelineProvider>
    </BrowserRouter>
  )
}
