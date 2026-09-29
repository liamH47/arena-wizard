import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { jsonBody, request } from '../api/client'
import type { Build, Pool, PoolWarning } from '../api/types'
import { Button, LoadError, Notice } from '../components/ui'
import { errorText, inputClass } from '../format'

// The review screen, ordered for a phone: is the pool all right, fix what is not, build.
// The card list and the raw export sit in closed sections below. Validation is advisory;
// the player is the authority on their own pool.

// An Arena export line: count, name, then "(SET) number", which a fix keeps.
const EXPORT_LINE = /^(\d+)\s+(.+?)\s+(\([A-Za-z0-9]{2,6}\)\s+\S+)\s*$/

function lines(text: string): string[] {
  return text.split(/\r\n|\n|\r/)
}

// Replace the name on one line with a suggestion, keeping its count, set, and number: the
// printing did not match, so the name decides, and the card resolves in the pool's set.
function withSuggestion(text: string, lineNo: number, suggestion: string): string | null {
  const all = lines(text)
  const match = EXPORT_LINE.exec((all[lineNo - 1] ?? '').trim())
  if (match === null) return null
  all[lineNo - 1] = `${match[1]} ${suggestion} ${match[3]}`
  return all.join('\n')
}

function withoutLine(text: string, lineNo: number): string {
  const all = lines(text)
  all.splice(lineNo - 1, 1)
  return all.join('\n')
}

function Unrecognised({
  warnings,
  text,
  busy,
  onFix,
}: {
  warnings: PoolWarning[]
  text: string
  busy: boolean
  onFix: (next: string) => void
}) {
  // Fix from the bottom up in practice: each fix saves, and the server renumbers warnings.
  return (
    <Notice tone="warn">
      <p className="font-medium">{warnings.length} lines not recognised; they will be in no deck.</p>
      <ul className="mt-2 space-y-3">
        {warnings.map((w, i) => (
          <li key={i} className="space-y-1">
            <p className="break-words">
              {w.line_no !== null && `Line ${w.line_no}: `}
              {w.raw || w.message}
            </p>
            {w.line_no !== null && (
              <div className="flex flex-wrap gap-2">
                {w.suggestions.map((s) => {
                  const next = withSuggestion(text, w.line_no ?? 0, s)
                  return (
                    next !== null && (
                      <Button key={s} disabled={busy} onClick={() => onFix(next)}>
                        Use {s}
                      </Button>
                    )
                  )
                })}
                <Button kind="danger" disabled={busy} onClick={() => onFix(withoutLine(text, w.line_no ?? 0))}>
                  Drop line
                </Button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </Notice>
  )
}

export default function PoolReview() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const [pool, setPool] = useState<Pool | null>(null)
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [attempt, setAttempt] = useState(0)
  // A build that finishes after the player left this page must not pull them back to it.
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  useEffect(() => {
    let live = true
    request<Pool>(`/api/pools/${id}`)
      .then((found) => {
        if (!live) return
        setPool(found)
        setText(found.export_text)
      })
      .catch((e: unknown) => {
        if (live) setError(errorText(e))
      })
    return () => {
      live = false
    }
  }, [id, attempt])

  const reload = useCallback(() => {
    setError(null)
    setAttempt((n) => n + 1)
  }, [])

  async function saveText(next: string): Promise<boolean> {
    setBusy(true)
    setError(null)
    try {
      const updated = await request<Pool>(`/api/pools/${id}`, {
        method: 'PUT',
        ...jsonBody({ export_text: next }),
      })
      if (mounted.current) {
        setPool(updated)
        setText(updated.export_text)
      }
      return true
    } catch (e) {
      if (mounted.current) setError(errorText(e))
      return false
    } finally {
      if (mounted.current) setBusy(false)
    }
  }

  async function build() {
    // Unsaved edits are saved first, so the decks always match the text on screen.
    if (pool !== null && text !== pool.export_text && !(await saveText(text))) return
    setBusy(true)
    setError(null)
    try {
      await request<Build>(`/api/pools/${id}/builds`, { method: 'POST' })
      if (mounted.current) void navigate(`/pools/${id}/decks`)
    } catch (e) {
      if (mounted.current) {
        setError(errorText(e))
        setBusy(false)
      }
    }
  }

  if (pool === null) {
    return error !== null ? <LoadError message={error} onRetry={reload} /> : <p className="text-slate-500">Loading…</p>
  }
  const [low, high] = pool.usual_range
  const unknown = pool.warnings.filter((w) => w.kind === 'unknown_name' || w.kind === 'unparsed')
  const other = pool.warnings.filter((w) => w.kind === 'wrong_set' || w.kind === 'alternate_printing')
  const outside = pool.nonbasic_count < low || pool.nonbasic_count > high
  const edited = text !== pool.export_text

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-xl font-semibold">{pool.set_code} pool</h1>
        <Link className="inline-flex min-h-11 items-center text-sm underline" to={`/pools/${id}/decks`}>
          Latest decks
        </Link>
      </div>
      <Notice tone={outside ? 'warn' : 'info'}>
        {pool.nonbasic_count} non-basic cards; {pool.set_code} pools usually run {low}–{high}.
      </Notice>
      {unknown.length > 0 && (
        <Unrecognised warnings={unknown} text={text} busy={busy} onFix={(next) => void saveText(next)} />
      )}
      {error !== null && <Notice tone="error">{error}</Notice>}

      <div className="sticky bottom-0 z-10 -mx-4 bg-slate-50/95 px-4 py-2 sm:static sm:mx-0 sm:bg-transparent sm:p-0">
        <Button kind="primary" className="w-full sm:w-auto" onClick={() => void build()} disabled={busy}>
          {busy ? 'Building decks…' : edited ? 'Save and build decks' : 'Build decks'}
        </Button>
      </div>

      {other.length > 0 && (
        <details className="rounded-md border border-slate-200 bg-white p-3 text-sm">
          <summary className="min-h-11 cursor-pointer py-2">{other.length} notes about printings and sets</summary>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            {other.map((w, i) => (
              <li key={i}>{w.message}</li>
            ))}
          </ul>
        </details>
      )}

      <details className="rounded-md border border-slate-200 bg-white p-3">
        <summary className="min-h-11 cursor-pointer py-2 font-semibold">Cards ({pool.entries.length} lines)</summary>
        <ul className="mt-2 grid gap-1 sm:grid-cols-2">
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
          <p className="mt-2 text-sm text-slate-600">
            Basic lands in the export (Arena supplies these freely):{' '}
            {pool.basics.map((b) => `${b.count} ${b.name}`).join(', ')}.
          </p>
        )}
      </details>

      <details className="rounded-md border border-slate-200 bg-white p-3" open={edited}>
        <summary className="min-h-11 cursor-pointer py-2 font-semibold">Edit export text</summary>
        <div className="mt-2 space-y-2">
          <textarea
            aria-label="Export text"
            className={`${inputClass} h-56 font-mono text-sm`}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <Button kind="primary" onClick={() => void saveText(text)} disabled={busy || !edited}>
            Save
          </Button>
        </div>
      </details>
    </div>
  )
}
