import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { jsonBody, request } from '../api/client'
import type { Build, Pool } from '../api/types'
import { Button, Notice } from '../components/ui'
import { errorText, inputClass } from '../format'

// The review screen: what the export resolved to, what did not, and the Build button.
// Validation is advisory; the player is the authority on their own pool.
export default function PoolReview() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const [pool, setPool] = useState<Pool | null>(null)
  const [text, setText] = useState('')
  const [editing, setEditing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    request<Pool>(`/api/pools/${id}`)
      .then((found) => {
        setPool(found)
        setText(found.export_text)
      })
      .catch((e: unknown) => setError(errorText(e)))
  }, [id])

  async function save() {
    setBusy(true)
    setError(null)
    try {
      const updated = await request<Pool>(`/api/pools/${id}`, {
        method: 'PUT',
        ...jsonBody({ export_text: text }),
      })
      setPool(updated)
      setEditing(false)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  async function build() {
    setBusy(true)
    setError(null)
    try {
      await request<Build>(`/api/pools/${id}/builds`, { method: 'POST' })
      void navigate(`/pools/${id}/decks`)
    } catch (e) {
      setError(errorText(e))
      setBusy(false)
    }
  }

  if (pool === null) {
    return error !== null ? <Notice tone="error">{error}</Notice> : <p className="text-slate-500">Loading…</p>
  }
  const [low, high] = pool.usual_range
  const unknown = pool.warnings.filter((w) => w.kind === 'unknown_name' || w.kind === 'unparsed')
  const other = pool.warnings.filter(
    (w) => w.kind === 'wrong_set' || w.kind === 'alternate_printing',
  )
  const outside = pool.nonbasic_count < low || pool.nonbasic_count > high

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-xl font-semibold">{pool.set_code} pool</h1>
        <Link className="min-h-11 text-sm underline" to={`/pools/${id}/decks`}>
          Latest decks
        </Link>
      </div>
      <Notice tone={outside ? 'warn' : 'info'}>
        {pool.nonbasic_count} non-basic cards; {pool.set_code} pools usually run {low}–{high}.
      </Notice>

      {other.length > 0 && (
        <details className="rounded-md border border-slate-200 bg-white p-3 text-sm">
          <summary className="min-h-11 cursor-pointer py-2">
            {other.length} notes about printings and sets
          </summary>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            {other.map((w, i) => (
              <li key={i}>{w.message}</li>
            ))}
          </ul>
        </details>
      )}

      <section className="space-y-2">
        <h2 className="font-semibold">Cards</h2>
        <ul className="grid gap-1 sm:grid-cols-2">
          {pool.entries.map((e) => (
            <li
              key={`${e.set_code}-${e.collector_number}`}
              className="flex items-center justify-between gap-2 rounded border border-slate-200 bg-white px-3 py-2 text-sm"
            >
              <span className="min-w-0 break-words">
                {e.count} {e.name}
              </span>
              <span className="shrink-0 text-xs text-slate-500">
                {e.colors || 'C'} · {e.rarity}
              </span>
            </li>
          ))}
        </ul>
        {pool.basics.length > 0 && (
          <p className="text-sm text-slate-600">
            Basic lands in the export (Arena supplies these freely):{' '}
            {pool.basics.map((b) => `${b.count} ${b.name}`).join(', ')}.
          </p>
        )}
      </section>

      <section className="space-y-2">
        <Button onClick={() => setEditing(!editing)}>{editing ? 'Stop editing' : 'Edit export text'}</Button>
        {editing && (
          <div className="space-y-2">
            <textarea
              className={`${inputClass} h-56 font-mono text-sm`}
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
            <Button kind="primary" onClick={() => void save()} disabled={busy}>
              Save
            </Button>
          </div>
        )}
      </section>

      {unknown.length > 0 && (
        <Notice tone="warn">
          <p className="font-medium">
            {unknown.length} lines not recognised; they will be in no deck.
          </p>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            {unknown.map((w, i) => (
              <li key={i}>
                {w.line_no !== null && `Line ${w.line_no}: `}
                {w.raw || w.message}
                {w.suggestions.length > 0 && ` (did you mean ${w.suggestions.join(', ')}?)`}
              </li>
            ))}
          </ul>
        </Notice>
      )}
      {error !== null && <Notice tone="error">{error}</Notice>}
      <Button kind="primary" className="w-full sm:w-auto" onClick={() => void build()} disabled={busy}>
        {busy ? 'Building decks…' : 'Build decks'}
      </Button>
    </div>
  )
}
