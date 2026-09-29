import Footer from './components/Footer'
import Header from './components/Header'

export default function App() {
  return (
    <div className="flex min-h-screen flex-col bg-slate-50 text-slate-900">
      <Header />
      <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-8">
        <h1 className="text-2xl font-semibold">Arena Wizard</h1>
        <p className="mt-2 text-slate-600">
          Sealed-deck recommendations for MTG Arena Best-of-One sealed. Under construction.
        </p>
      </main>
      <Footer />
    </div>
  )
}
