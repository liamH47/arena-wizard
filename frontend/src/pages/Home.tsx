import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'

import { jsonBody, newId, request } from '../api/client'
import type { Pool, PoolListItem, SetInfo } from '../api/types'
import { Button, LoadError, Notice } from '../components/ui'
import { errorText, inputClass, when } from '../format'

export default function Home() {
  const navigate = useNavigate()
  const [sets, setSets] = useState<SetInfo[]>([])
  const [pools, setPools] = useState<PoolListItem[]>([])
  const [setCode, setSetCode] = useState('')
  const [text, setText] = useState('')
  const [loadError, setLoadError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [attempt, setAttempt] = useState(0)
  // One id per pool being created, so a retried or double-tapped submit replays the same
  // create instead of making a second pool. After a failed submit, changing the text mints a
  // new id: the failed one may have reached the server, and the same id with different
  // text would be refused.
  const poolId = useRef(newId())
  const failed = useRef(false)

  useEffect(() => {
    let live = true
    Promise.all([request<SetInfo[]>('/api/sets'), request<PoolListItem[]>('/api/pools')])
      .then(([foundSets, foundPools]) => {
        if (!live) return
        setSets(foundSets)
        setSetCode((current) => current || (foundSets[0]?.code ?? ''))
        setPools(foundPools)
      })
      .catch((e: unknown) => {
        if (live) setLoadError(errorText(e))
      })
    return () => {
      live = false
    }
  }, [attempt])

  const reload = useCallback(() => {
    setLoadError(null)
    setAttempt((n) => n + 1)
  }, [])

  function changeText(next: string) {
    if (failed.current) {
      poolId.current = newId()
      failed.current = false
    }
    setText(next)
  }

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
      failed.current = true
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid gap-8 md:grid-cols-2">
      <section className="space-y-3">
        <h1 className="text-xl font-semibold">New pool</h1>
        {loadError !== null && <LoadError message={loadError} onRetry={reload} />}
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
              onChange={(e) => changeText(e.target.value)}
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
                  className="flex min-h-11 flex-col justify-center gap-0.5 px-3 py-2 hover:bg-slate-50"
                  to={p.has_build ? `/pools/${p.id}/decks` : `/pools/${p.id}`}
                >
                  <span className="flex items-baseline justify-between gap-2">
                    <span className="font-medium">
                      {p.set_code} {p.has_build ? '· decks' : '· not built yet'}
                    </span>
                    <span className="text-sm text-slate-600">{when(p.created_at)}</span>
                  </span>
                  {p.hint && <span className="truncate text-xs text-slate-500">{p.hint}</span>}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
