import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router'

import { jsonBody, newId, request } from '../api/client'
import type { Build, Deck, Run } from '../api/types'
import { Button, Notice } from '../components/ui'
import { errorText, inputClass } from '../format'

function points(value: number): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(1)}`
}

function CardValues({ deck }: { deck: Deck }) {
  const values = [...deck.values].sort((a, b) => b.q - a.q || a.name.localeCompare(b.name))
  return (
    <details className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm">
      <summary className="min-h-11 cursor-pointer py-2 font-medium">
        Card values (points; ± is the uncertainty)
      </summary>
      <ul className="mt-2 space-y-2">
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
          </li>
        ))}
      </ul>
    </details>
  )
}

function CopyList({ text }: { text: string }) {
  const [copied, setCopied] = useState<'no' | 'yes' | 'failed'>('no')
  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setCopied('yes')
    } catch {
      setCopied('failed')
    }
  }
  return (
    <div className="space-y-2">
      <pre className="max-h-72 overflow-auto rounded-md border border-slate-200 bg-white p-3 text-sm whitespace-pre-wrap">
        {text}
      </pre>
      <div className="flex items-center gap-3">
        <Button kind="primary" onClick={() => void copy()}>
          Copy list
        </Button>
        {copied === 'yes' && <span className="text-sm text-emerald-700">Copied.</span>}
        {copied === 'failed' && (
          <span className="text-sm text-red-700">Could not copy; select the list instead.</span>
        )}
      </div>
    </div>
  )
}

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
  const [eventName, setEventName] = useState('')
  const [notes, setNotes] = useState('')
  const [message, setMessage] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null)
  const runId = useRef(newId())

  async function submit(event: FormEvent) {
    event.preventDefault()
    setMessage(null)
    try {
      await request<Run>('/api/runs', {
        method: 'POST',
        ...jsonBody({
          id: runId.current,
          build_id: buildId,
          deck_index: deckIndex,
          wins,
          losses,
          event_name: eventName,
          notes,
        }),
      })
      runId.current = newId()
      setMessage({ tone: 'ok', text: `Recorded ${wins}-${losses}. Edit it later under Results.` })
    } catch (e) {
      setMessage({ tone: 'error', text: errorText(e) })
    }
  }

  return (
    <form className="space-y-3 rounded-md border border-slate-200 bg-white p-3" onSubmit={(e) => void submit(e)}>
      <h4 className="font-medium">Record result</h4>
      <Stepper label="Wins" value={wins} onChange={setWins} />
      <Stepper label="Losses" value={losses} onChange={setLosses} />
      <input
        className={inputClass}
        placeholder="Event name (optional)"
        value={eventName}
        onChange={(e) => setEventName(e.target.value)}
      />
      <input
        className={inputClass}
        placeholder="Notes (optional)"
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
      />
      {message !== null && <Notice tone={message.tone}>{message.text}</Notice>}
      <Button kind="primary" type="submit">
        Record result
      </Button>
    </form>
  )
}

function DeckCard({ deck, rank, buildId }: { deck: Deck; rank: number; buildId: number }) {
  return (
    <article className="space-y-3 rounded-lg border border-slate-200 bg-white p-4" data-testid="deck">
      <header className="flex flex-wrap items-baseline gap-2">
        <h3 className="text-lg font-semibold">
          #{rank} {deck.label}
        </h3>
        <span className="text-sm text-slate-600">score {deck.total.toFixed(1)}</span>
        {deck.toss_up && (
          <span className="rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-900">toss-up</span>
        )}
      </header>
      <ul className="list-disc space-y-1 pl-5 text-sm">
        {deck.explanations.map((line, i) => (
          <li key={i} className="break-words">
            {line}
          </li>
        ))}
      </ul>
      <details className="text-sm">
        <summary className="min-h-11 cursor-pointer py-2 font-medium">Breakdown (score points)</summary>
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
      </details>
      <CardValues deck={deck} />
      <details className="text-sm">
        <summary className="min-h-11 cursor-pointer py-2 font-medium">Card images</summary>
        <div className="mt-2 grid grid-cols-3 gap-2 sm:grid-cols-5">
          {deck.spells
            .filter((s) => s.image_uri !== null)
            .map((s) => (
              <img
                key={s.name}
                src={s.image_uri ?? ''}
                alt={s.name}
                loading="lazy"
                className="w-full rounded"
              />
            ))}
        </div>
      </details>
      <h4 className="font-medium">Deck (click these into Arena)</h4>
      <CopyList text={deck.arena_list} />
      <RecordResult buildId={buildId} deckIndex={deck.deck_index} />
    </article>
  )
}

export default function Decks() {
  const { id = '' } = useParams()
  const [build, setBuild] = useState<Build | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    request<Build>(`/api/pools/${id}/builds/latest`)
      .then(setBuild)
      .catch((e: unknown) => setError(errorText(e)))
  }, [id])

  async function rebuild() {
    setBusy(true)
    setError(null)
    try {
      setBuild(await request<Build>(`/api/pools/${id}/builds`, { method: 'POST' }))
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Decks</h1>
        <Link className="min-h-11 text-sm underline" to={`/pools/${id}`}>
          Back to the pool
        </Link>
      </div>
      {error !== null && <Notice tone="error">{error}</Notice>}
      {build !== null && !build.current && (
        <Notice tone="warn">
          <span className="mr-3">Pool or pastes changed since this build — Build again.</span>
          <Button kind="primary" onClick={() => void rebuild()} disabled={busy}>
            {busy ? 'Building…' : 'Build again'}
          </Button>
        </Notice>
      )}
      {build === null && error === null && <p className="text-slate-500">Loading…</p>}
      {build !== null && (
        <>
          <pre
            className="overflow-x-auto rounded-md border border-slate-200 bg-white p-3 text-xs whitespace-pre-wrap"
            data-testid="data-block"
          >
            {build.data_lines.join('\n')}
          </pre>
          {build.refusal !== null && <Notice tone="warn">{build.refusal}</Notice>}
          <div className="space-y-6">
            {build.decks.map((deck, i) => (
              <DeckCard key={deck.deck_index} deck={deck} rank={i + 1} buildId={build.id} />
            ))}
          </div>
          <Button onClick={() => void rebuild()} disabled={busy}>
            {busy ? 'Building…' : 'Build again'}
          </Button>
        </>
      )}
    </div>
  )
}
