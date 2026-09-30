import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router'

import { ApiError, jsonBody, newId, request } from '../api/client'
import type { Adjustment, Build, Deck, Run } from '../api/types'
import { Button, LoadError, Notice } from '../components/ui'
import { errorText, inputClass } from '../format'

// The deck page, ordered for a phone between matches: which deck, the list to click into
// Arena, and the result. Everything that explains the ranking sits in closed sections below.

function points(value: number): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(1)}`
}

// ---- the Data block: what the build rests on, collapsed to one status line ----------------

const DATA_ROWS = ['Win rates', 'Draft data', 'Grades', 'Bombs']

function dataStatus(lines: string[]): string {
  const parts: string[] = []
  for (const row of DATA_ROWS) {
    const line = lines.find((l) => l.trimStart().startsWith(row))
    if (line === undefined) continue
    const state = line.trimStart().slice(row.length).trim().split(/\s+/)[0] ?? ''
    parts.push(`${row.toLowerCase()} ${state}`)
  }
  return parts.length > 0 ? `Data: ${parts.join(' · ')}` : 'Data'
}

function DataBlock({ build }: { build: Build }) {
  const missing = build.refusal !== null || build.data_lines.some((l) => l.includes('missing'))
  return (
    <div className="space-y-2">
      <details className="rounded-md border border-slate-200 bg-white" open={build.refusal !== null}>
        <summary className="min-h-11 cursor-pointer px-3 py-2 text-sm font-medium">
          {dataStatus(build.data_lines)}
        </summary>
        <pre
          className="overflow-x-auto border-t border-slate-100 p-3 text-xs whitespace-pre-wrap"
          data-testid="data-block"
        >
          {build.data_lines.join('\n')}
        </pre>
      </details>
      {missing && (
        <Link className="inline-flex min-h-11 items-center text-sm underline" to="/pastes">
          Add data
        </Link>
      )}
    </div>
  )
}

// ---- the list to click into Arena ----------------------------------------------------------

type Row = { name: string; count: number }

function groups(deck: Deck): { title: string; rows: Row[] }[] {
  const byCurve = (a: Deck['spells'][number], b: Deck['spells'][number]) =>
    a.mana_value - b.mana_value || a.name.localeCompare(b.name)
  const creatures = deck.spells.filter((s) => s.type_line.includes('Creature')).sort(byCurve)
  const others = deck.spells.filter((s) => !s.type_line.includes('Creature')).sort(byCurve)
  const total = (rows: Row[]) => rows.reduce((sum, r) => sum + r.count, 0)
  return [
    { title: 'Creatures', rows: creatures },
    { title: 'Other spells', rows: others },
    { title: 'Lands', rows: deck.lands },
  ]
    .filter((g) => g.rows.length > 0)
    .map((g) => ({ title: `${g.title} (${total(g.rows)})`, rows: g.rows }))
}

function ArenaList({ deck }: { deck: Deck }) {
  // Tap a row once it is clicked into Arena; Arena cannot import during a Limited event.
  const [done, setDone] = useState<Set<string>>(new Set())
  const [copied, setCopied] = useState<'no' | 'yes' | 'failed'>('no')
  const cards = [...deck.spells, ...deck.lands].reduce((sum, r) => sum + r.count, 0)

  function toggle(key: string) {
    setDone((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(deck.arena_list)
      setCopied('yes')
    } catch {
      setCopied('failed')
    }
  }

  return (
    <section className="space-y-3" data-testid="arena-list">
      <h4 className="font-medium">
        Deck to click into Arena <span className="text-slate-600">· {cards} cards</span>
      </h4>
      {groups(deck).map((group) => (
        <div key={group.title}>
          <h5 className="text-sm font-semibold text-slate-700">{group.title}</h5>
          <ul className="divide-y divide-slate-100 rounded-md border border-slate-200 bg-white">
            {group.rows.map((row) => {
              const key = `${group.title}-${row.name}`
              const struck = done.has(key)
              return (
                <li key={key}>
                  <button
                    type="button"
                    data-testid="list-row"
                    aria-pressed={struck}
                    onClick={() => toggle(key)}
                    className={`flex min-h-11 w-full items-center gap-3 px-3 text-left text-base ${
                      struck ? 'text-slate-400 line-through' : ''
                    }`}
                  >
                    <span className="w-6 text-right tabular-nums">{row.count}</span>
                    <span className="min-w-0 break-words">{row.name}</span>
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      ))}
      <div className="flex items-center gap-3">
        <Button onClick={() => void copy()}>Copy list</Button>
        {copied === 'yes' && <span className="text-sm text-emerald-700">Copied.</span>}
        {copied === 'failed' && <span className="text-sm text-red-700">Could not copy.</span>}
      </div>
    </section>
  )
}

// ---- recording a result: one run per event, edited as the event goes on --------------------

function Stepper({ label, value, onChange }: { label: string; value: number; onChange: (n: number) => void }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-14 text-sm font-medium">{label}</span>
      <Button aria-label={`fewer ${label.toLowerCase()}`} onClick={() => onChange(Math.max(0, value - 1))}>
        −
      </Button>
      <span className="w-6 text-center tabular-nums" aria-live="polite">
        {value}
      </span>
      <Button aria-label={`more ${label.toLowerCase()}`} onClick={() => onChange(Math.min(20, value + 1))}>
        +
      </Button>
    </div>
  )
}

function RecordResult({ buildId, deckIndex }: { buildId: number; deckIndex: number }) {
  const [wins, setWins] = useState(0)
  const [losses, setLosses] = useState(0)
  const [recorded, setRecorded] = useState<Run | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null)
  // One id per event: the first save creates the run, every later save edits it, so
  // updating the tally after each match never records a second run.
  const [runId, setRunId] = useState(newId)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setMessage(null)
    try {
      if (recorded === null) {
        const run = await request<Run>('/api/runs', {
          method: 'POST',
          ...jsonBody({ id: runId, build_id: buildId, deck_index: deckIndex, wins, losses }),
        })
        setRecorded(run)
        setMessage({ tone: 'ok', text: `Recorded ${run.wins}-${run.losses}.` })
      } else {
        const run = await request<Run>(`/api/runs/${runId}`, {
          method: 'PATCH',
          ...jsonBody({ wins, losses }),
        })
        setRecorded(run)
        setMessage({ tone: 'ok', text: `Updated to ${run.wins}-${run.losses}.` })
      }
    } catch (e) {
      setMessage({ tone: 'error', text: errorText(e) })
    } finally {
      setBusy(false)
    }
  }

  function another() {
    setRunId(newId())
    setRecorded(null)
    setWins(0)
    setLosses(0)
    setMessage(null)
  }

  return (
    <form className="space-y-3 rounded-md border border-slate-200 bg-white p-3" onSubmit={(e) => void submit(e)}>
      <h4 className="font-medium">{recorded === null ? 'Record result' : 'This event'}</h4>
      <Stepper label="Wins" value={wins} onChange={setWins} />
      <Stepper label="Losses" value={losses} onChange={setLosses} />
      {message !== null && <Notice tone={message.tone}>{message.text}</Notice>}
      <div className="flex flex-wrap gap-2">
        <Button kind="primary" type="submit" disabled={busy}>
          {busy ? 'Saving…' : recorded === null ? 'Record result' : 'Update result'}
        </Button>
        {recorded !== null && <Button onClick={another}>Record another event</Button>}
      </div>
    </form>
  )
}

// ---- why this deck -------------------------------------------------------------------------

// A group-shared correction to one card (decision 0011), starting from what the group has
// saved. Saving never reloads the build: the deck being piloted stays as it is, and the
// change applies at the next "Build again".
function AdjustCard({ adjust, name }: { adjust: AdjustProps; name: string }) {
  const { setCode, building } = adjust
  const current = adjust.saved.get(name)
  const [bomb, setBomb] = useState<'' | 'add' | 'remove'>(current?.bomb ?? '')
  const [delta, setDelta] = useState(current?.q_delta ?? 0)
  const [note, setNote] = useState(current?.note ?? '')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null)
  const path = `/api/adjustments/${encodeURIComponent(setCode)}/${encodeURIComponent(name)}`

  async function save(clear: boolean) {
    setBusy(true)
    setMessage(null)
    try {
      await request(
        path,
        clear
          ? { method: 'DELETE' }
          : { method: 'PUT', ...jsonBody({ bomb: bomb || null, q_delta: delta || null, note }) },
      )
      setMessage({ tone: 'ok', text: `${clear ? 'Cleared' : 'Saved'} for the group; it applies when you build again.` })
      adjust.refresh()
    } catch (e) {
      setMessage({ tone: 'error', text: errorText(e) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <details>
      <summary className="min-h-11 cursor-pointer py-2 text-slate-700">Adjust</summary>
      <div className="space-y-2 pb-2">
        <label className="block">
          Bomb
          <select
            className={`${inputClass} mt-1`}
            value={bomb}
            onChange={(e) => setBomb(e.target.value as '' | 'add' | 'remove')}
          >
            <option value="">As the data says</option>
            <option value="add">Always a bomb</option>
            <option value="remove">Never a bomb</option>
          </select>
        </label>
        <div className="flex items-center gap-2">
          <span className="w-14 font-medium">Value</span>
          <Button aria-label="lower value" onClick={() => setDelta((d) => Math.max(-10, d - 0.5))}>
            −
          </Button>
          <span className="w-12 text-center tabular-nums" aria-live="polite">
            {points(delta)}
          </span>
          <Button aria-label="raise value" onClick={() => setDelta((d) => Math.min(10, d + 0.5))}>
            +
          </Button>
        </div>
        <label className="block">
          Note
          <input className={`${inputClass} mt-1`} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        {message !== null && <Notice tone={message.tone}>{message.text}</Notice>}
        <div className="flex flex-wrap gap-2">
          <Button kind="primary" disabled={busy || building || (bomb === '' && delta === 0)} onClick={() => void save(false)}>
            Save for the group
          </Button>
          <Button disabled={busy || current === undefined} onClick={() => void save(true)}>
            Clear
          </Button>
        </div>
      </div>
    </details>
  )
}

function CardValues({ deck, adjust }: { deck: Deck; adjust: AdjustProps }) {
  const values = [...deck.values].sort((a, b) => b.q - a.q || a.name.localeCompare(b.name))
  return (
    <div className="space-y-1">
      <h5 className="font-medium">Card values (points; ± is the uncertainty)</h5>
      <ul className="space-y-2">
        {values.map((v) => (
          <li key={v.name} className="break-words">
            <span className="font-medium">{v.name}</span>: {points(v.q)} ±{v.se.toFixed(1)} ·{' '}
            {v.basis}
            {v.observed !== null && ` · ${(100 * v.observed).toFixed(1)}% in hand (n=${v.games.toLocaleString()})`}
            {v.grades.length > 0 && (
              <span className="block text-slate-600">
                Grades: {v.grades.map((g) => `${g.source} ${g.grade}`).join('; ')}
              </span>
            )}
            {v.layers.length > 1 && (
              <span className="block text-slate-600">
                Weight: {v.layers.map((l) => `${l.name} ${Math.round(100 * l.share)}%`).join(', ')}
              </span>
            )}
            {v.adjustment !== null && (
              <span className="block text-slate-600">
                Adjusted {points(v.adjustment.q_delta)} by {v.adjustment.by}
              </span>
            )}
            <AdjustCard adjust={adjust} name={v.name} />
          </li>
        ))}
      </ul>
    </div>
  )
}

// Saving waits while a build runs, so a build that missed the change is never shown as current.
type AdjustProps = { setCode: string; saved: Map<string, Adjustment>; refresh: () => void; building: boolean }

function WhyThisDeck({ deck, adjust }: { deck: Deck; adjust: AdjustProps }) {
  return (
    <details className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm">
      <summary className="min-h-11 cursor-pointer py-2 font-medium">Why this deck</summary>
      <div className="mt-2 space-y-4">
        <ul className="list-disc space-y-1 pl-5">
          {deck.explanations.map((line, i) => (
            <li key={i} className="break-words">
              {line}
            </li>
          ))}
        </ul>
        <div>
          <h5 className="font-medium">Breakdown (score points)</h5>
          <dl className="mt-1 divide-y divide-slate-100">
            {deck.terms.map((t) => (
              <div key={t.name} className="flex flex-wrap justify-between gap-x-3 py-1">
                <dt>{t.name.replace(/_/g, ' ')}</dt>
                <dd className="tabular-nums">
                  {points(t.contribution)} <span className="text-slate-500">{t.detail}</span>
                </dd>
              </div>
            ))}
          </dl>
        </div>
        <CardValues deck={deck} adjust={adjust} />
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
          {deck.spells
            .filter((s) => s.image_uri !== null)
            .map((s) => (
              <img key={s.name} src={s.image_uri ?? ''} alt={s.name} loading="lazy" className="w-full rounded" />
            ))}
        </div>
      </div>
    </details>
  )
}

// The comparison with the next deck, first sentence only: "Ranked above UB …", "Within …".
function tradeOff(deck: Deck): string | null {
  const line = deck.explanations.find((l) => /^(Ranked above|Within|Ahead of)/.test(l))
  if (line === undefined) return null
  const end = line.indexOf('. ')
  return end === -1 ? line : line.slice(0, end + 1)
}

function DeckCard({
  deck,
  rank,
  buildId,
  stale,
  adjust,
}: {
  deck: Deck
  rank: number
  buildId: number
  stale: boolean
  adjust: AdjustProps
}) {
  const [open, setOpen] = useState(rank === 1)
  const summary = tradeOff(deck)
  return (
    <article
      className={`space-y-3 rounded-lg border border-slate-200 bg-white p-4 ${stale ? 'opacity-60' : ''}`}
      data-testid="deck"
    >
      <header className="flex flex-wrap items-baseline gap-2">
        <h3 className="text-lg font-semibold">
          #{rank} {deck.label}
        </h3>
        <span className="text-sm text-slate-600">score {deck.total.toFixed(1)}</span>
        {deck.toss_up && (
          <span className="rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-900">toss-up</span>
        )}
        {!open && (
          <Button className="ml-auto" onClick={() => setOpen(true)}>
            Show
          </Button>
        )}
      </header>
      {open && (
        <>
          {summary !== null && <p className="text-sm text-slate-700">{summary}</p>}
          {stale ? (
            <p className="text-sm text-slate-600">Build again to see this deck’s list.</p>
          ) : (
            <>
              <ArenaList deck={deck} />
              <RecordResult buildId={buildId} deckIndex={deck.deck_index} />
            </>
          )}
          <WhyThisDeck deck={deck} adjust={adjust} />
        </>
      )}
    </article>
  )
}

// ---- the page --------------------------------------------------------------------------------

export default function Decks() {
  const { id = '' } = useParams()
  const [build, setBuild] = useState<Build | null>(null)
  const [none, setNone] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let live = true
    request<Build>(`/api/pools/${id}/builds/latest`)
      .then((found) => {
        if (live) setBuild(found)
      })
      .catch((e: unknown) => {
        if (!live) return
        if (e instanceof ApiError && e.status === 404) setNone(true)
        else setError(errorText(e))
      })
    return () => {
      live = false
    }
  }, [id, attempt])

  const [adjustments, setAdjustments] = useState(new Map<string, Adjustment>())
  const setCode = build?.set_code
  const refreshAdjustments = useCallback(() => {
    if (setCode === undefined) return
    request<Adjustment[]>(`/api/adjustments?set_code=${encodeURIComponent(setCode)}`)
      .then((found) => setAdjustments(new Map(found.map((a) => [a.name, a]))))
      .catch(() => undefined) // the forms start blank; saving still works
  }, [setCode])
  useEffect(refreshAdjustments, [refreshAdjustments])

  const reload = useCallback(() => {
    setError(null)
    setNone(false)
    setAttempt((n) => n + 1)
  }, [])

  async function rebuild() {
    setBusy(true)
    setError(null)
    try {
      setBuild(await request<Build>(`/api/pools/${id}/builds`, { method: 'POST' }))
      setNone(false)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  const buildButton = (label: string) => (
    <Button kind="primary" onClick={() => void rebuild()} disabled={busy}>
      {busy ? 'Building…' : label}
    </Button>
  )

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Decks</h1>
        <Link className="inline-flex min-h-11 items-center text-sm underline" to={`/pools/${id}`}>
          Back to the pool
        </Link>
      </div>
      {error !== null && build === null && <LoadError message={error} onRetry={reload} />}
      {error !== null && build !== null && <Notice tone="error">{error}</Notice>}
      {none && build === null && (
        <Notice tone="info">
          <p className="mb-2">No decks built for this pool yet.</p>
          {buildButton('Build decks')}
        </Notice>
      )}
      {build === null && !none && error === null && <p className="text-slate-500">Loading…</p>}
      {build !== null && (
        <>
          {!build.current && (
            <Notice tone="warn">
              <p className="mb-2">
                The pool, pastes, card adjustments, or the app changed since this build — build again.
              </p>
              {buildButton('Build again')}
            </Notice>
          )}
          <DataBlock build={build} />
          {build.refusal !== null && <Notice tone="warn">{build.refusal}</Notice>}
          <div className="space-y-6">
            {build.decks.map((deck, i) => (
              <DeckCard
                key={`${build.id}-${deck.deck_index}`}
                deck={deck}
                rank={i + 1}
                buildId={build.id}
                stale={!build.current}
                adjust={{ setCode: build.set_code, saved: adjustments, refresh: refreshAdjustments, building: busy }}
              />
            ))}
          </div>
          {build.current && <Button onClick={() => void rebuild()} disabled={busy}>{busy ? 'Building…' : 'Build again'}</Button>}
        </>
      )}
    </div>
  )
}
