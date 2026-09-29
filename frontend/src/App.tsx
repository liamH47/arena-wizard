import { BrowserRouter, Navigate, Route, Routes } from 'react-router'

import Footer from './components/Footer'
import Header from './components/Header'
import { Button, Notice } from './components/ui'
import WakingBanner from './components/WakingBanner'
import { MeProvider } from './me'
import { useMeState } from './me-context'
import Decks from './pages/Decks'
import Home from './pages/Home'
import Login from './pages/Login'
import Pastes from './pages/Pastes'
import PoolReview from './pages/PoolReview'
import Runs from './pages/Runs'

function Signed({ children }: { children: React.ReactNode }) {
  const { me, error, retry } = useMeState()
  if (error !== null) {
    // Not "signed out": /api/me always answers when the server is up, so this is a server
    // still waking. Never send the player to the login page for it.
    return (
      <Notice tone="warn">
        <p>The server is still waking up. {error}</p>
        <Button className="mt-2" onClick={retry}>
          Try again
        </Button>
      </Notice>
    )
  }
  if (me === null) return <p className="text-slate-500">Loading…</p>
  if (me.auth === 'google' && me.user === null) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <BrowserRouter>
      <MeProvider>
        <div className="flex min-h-screen flex-col bg-slate-50 text-slate-900">
          <WakingBanner />
          <Header />
          <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6">
            <Routes>
              <Route path="/login" element={<Login />} />
              <Route path="/" element={<Signed><Home /></Signed>} />
              <Route path="/pools/:id" element={<Signed><PoolReview /></Signed>} />
              <Route path="/pools/:id/decks" element={<Signed><Decks /></Signed>} />
              <Route path="/runs" element={<Signed><Runs /></Signed>} />
              <Route path="/pastes" element={<Signed><Pastes /></Signed>} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </main>
          <Footer />
        </div>
      </MeProvider>
    </BrowserRouter>
  )
}
