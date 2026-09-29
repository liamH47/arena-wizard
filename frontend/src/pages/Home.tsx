import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'

import { jsonBody, newId, request } from '../api/client'
import type { Pool, PoolSummary, SetInfo } from '../api/types'
import { Button, Notice } from '../components/ui'
import { errorText, inputClass, when } from '../format'

export default function Home() {
  const navigate = useNavigate()
  const [sets, setSets] = useState<SetInfo[]>([])
  const [pools, setPools] = useState<PoolSummary[]>([])
  const [setCode, setSetCode] = useState('')
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // One id per pool being created, so a retried or double-tapped submit replays the same
  // create instead of making a second pool.
  const poolId = useRef(newId())

  useEffect(() => {
    request<SetInfo[]>('/api/sets')
      .then((found) => {
        setSets(found)
        setSetCode((current) => current || (found[0]?.code ?? ''))
      })
      .catch((e: unknown) => setError(errorText(e)))
    request<PoolSummary[]>('/api/pools')
      .then(setPools)
      .catch((e: unknown) => setError(errorText(e)))
  }, [])

  async function create(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const pool = await request<Pool>('/api/pools', {
        method: 'POST',
        ...jsonBody({ id: poolId.current, set_code: setCode, format: 'bo1_sealed', export_text: text }),
      })
      poolId.current = newId()
      void navigate(`/pools/${pool.id}`)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid gap-8 md:grid-cols-2">
      <section className="space-y-3">
        <h1 className="text-xl font-semibold">New pool</h1>
        <form className="space-y-3" onSubmit={(e) => void create(e)}>
          <label className="block text-sm font-medium">
            Set
            <select
              aria-label="Set"
              className={`${inputClass} mt-1`}
              value={setCode}
              onChange={(e) => setSetCode(e.target.value)}
            >
              {sets.map((s) => (
                <option key={s.code} value={s.code}>
                  {s.name} ({s.code})
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm font-medium">
            Arena export
            <textarea
              aria-label="Arena export"
              className={`${inputClass} mt-1 h-56 font-mono text-sm`}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="1 Card Name (SET) 123"
              required
            />
          </label>
          <p className="text-sm text-slate-600">
            In Arena, add every card in the pool to the deck, press Export, paste here;
            duplicates are normal.
          </p>
          {error !== null && <Notice tone="error">{error}</Notice>}
          <Button kind="primary" type="submit" disabled={busy || !text.trim() || !setCode}>
            {busy ? 'Reading the pool…' : 'Review pool'}
          </Button>
        </form>
      </section>
      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Your pools</h2>
        {pools.length === 0 ? (
          <p className="text-sm text-slate-600">No pools yet.</p>
        ) : (
          <ul className="divide-y divide-slate-200 rounded-md border border-slate-200 bg-white">
            {pools.map((p) => (
              <li key={p.id}>
                <Link
                  className="flex min-h-11 items-center justify-between gap-2 px-3 py-2 hover:bg-slate-50"
                  to={`/pools/${p.id}`}
                >
                  <span className="font-medium">{p.set_code}</span>
                  <span className="text-sm text-slate-600">{when(p.created_at)}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
