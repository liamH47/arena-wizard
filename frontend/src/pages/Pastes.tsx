import { useCallback, useEffect, useState, type ChangeEvent, type FormEvent } from 'react'

import { ApiError, decodeUpload, jsonBody, request } from '../api/client'
import type { Paste, PasteResult, PasteSource, SetInfo } from '../api/types'
import { Button, Notice } from '../components/ui'
import { errorText, inputClass, when } from '../format'
import { useMe } from '../me-context'

// Data a friend exported or copied by hand (decisions 0005, 0007, 0008). The page never
// reads the clipboard on its own, and a paste's link is only a label.
const EVENT_TYPES = [
  { value: 'ArenaDirect_Sealed', label: 'Arena Direct Sealed' },
  { value: 'PremierDraft', label: 'Premier Draft' },
  { value: 'Sealed', label: 'Sealed' },
]

export default function Pastes() {
  const me = useMe()
  const [sets, setSets] = useState<SetInfo[]>([])
  const [sources, setSources] = useState<PasteSource[]>([])
  const [setCode, setSetCode] = useState('')
  const [pastes, setPastes] = useState<Paste[]>([])
  const [dataset, setDataset] = useState<'grades' | 'card-data'>('grades')
  const [sourceId, setSourceId] = useState('')
  const [ownName, setOwnName] = useState('')
  const [eventType, setEventType] = useState('')
  const [copiedOn, setCopiedOn] = useState('')
  const [publishedOn, setPublishedOn] = useState('')
  const [url, setUrl] = useState('')
  const [replace, setReplace] = useState(false)
  const [text, setText] = useState('')
  const [result, setResult] = useState<{ tone: 'ok' | 'error'; lines: string[] } | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    request<SetInfo[]>('/api/sets')
      .then((found) => {
        setSets(found)
        setSetCode((current) => current || (found[0]?.code ?? ''))
      })
      .catch((e: unknown) => setResult({ tone: 'error', lines: [errorText(e)] }))
    request<PasteSource[]>('/api/pastes/sources')
      .then(setSources)
      .catch((e: unknown) => setResult({ tone: 'error', lines: [errorText(e)] }))
  }, [])

  const load = useCallback(() => {
    if (!setCode) return
    request<Paste[]>(`/api/pastes?set_code=${encodeURIComponent(setCode)}`)
      .then(setPastes)
      .catch((e: unknown) => setResult({ tone: 'error', lines: [errorText(e)] }))
  }, [setCode])

  useEffect(load, [load])

  const choices = sources.filter((s) => s.dataset === dataset)
  const chosenSource = sourceId === 'own' ? `own-${ownName.trim().toLowerCase()}` : sourceId

  async function readFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    // Bytes, decoded like the server does: Excel saves UTF-16 or Windows-1252, and reading
    // those as UTF-8 would garble names like "Dáin".
    if (file !== undefined) setText(decodeUpload(await file.arrayBuffer()))
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setResult(null)
    try {
      const body = {
        set_code: setCode,
        dataset,
        source_id: chosenSource,
        event_type: dataset === 'card-data' ? eventType : null,
        copied_on: copiedOn || null,
        published_on: publishedOn || null,
        url: url.trim() || null,
        replace,
        text,
      }
      const saved = await request<PasteResult>('/api/pastes', { method: 'POST', ...jsonBody(body) })
      setResult({ tone: 'ok', lines: saved.messages })
      setText('')
      load()
    } catch (e) {
      setResult({ tone: 'error', lines: [errorText(e)] })
    } finally {
      // "Replace even if smaller" is for one paste only; leaving it on would skip the
      // guard against a truncated copy on every later paste.
      setReplace(false)
      setBusy(false)
    }
  }

  function mayDelete(paste: Paste): boolean {
    return me !== null && (me.owner || paste.pasted_by === me.user?.user_id)
  }

  async function remove(shown: Paste) {
    // Check the list again first: a friend may have replaced this paste since the page
    // loaded, and the confirmation must name what would actually be deleted.
    let current: Paste | undefined
    try {
      const fresh = await request<Paste[]>(`/api/pastes?set_code=${encodeURIComponent(shown.set_code)}`)
      setPastes(fresh)
      current = fresh.find((p) => p.key === shown.key)
    } catch (e) {
      setResult({ tone: 'error', lines: [errorText(e)] })
      return
    }
    if (current === undefined) return
    const paste = current
    const who = paste.pasted_by === me?.user?.user_id ? 'you' : paste.pasted_by
    if (!window.confirm(`Delete "${paste.label}" (${paste.rows} rows, pasted by ${who})? Everyone’s next build stops using it.`)) {
      return
    }
    try {
      await request(`/api/pastes/${paste.set_code}/${paste.key}`, { method: 'DELETE' })
      load()
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) load()
      else if (e instanceof ApiError && e.status === 403)
        setResult({
          tone: 'error',
          lines: ['Only whoever pasted this, or the owner, can delete it. Ask them, or paste a correction today.'],
        })
      else setResult({ tone: 'error', lines: [errorText(e)] })
    }
  }

  return (
    <div className="grid gap-8 md:grid-cols-2">
      <section className="space-y-3">
        <h1 className="text-xl font-semibold">Paste data</h1>
        <Notice tone="info">
          Paste only data you copied or exported yourself, by hand. No scripts or automated
          downloads. Pastes are private to this group; one per source per day, and pasting
          again the same day replaces it.
        </Notice>
        <form className="space-y-3" onSubmit={(e) => void submit(e)}>
          <label className="block text-sm font-medium">
            Set
            <select aria-label="Set" className={`${inputClass} mt-1`} value={setCode} onChange={(e) => setSetCode(e.target.value)}>
              {sets.map((s) => (
                <option key={s.code} value={s.code}>
                  {s.name} ({s.code})
                </option>
              ))}
            </select>
          </label>
          <fieldset className="space-y-1">
            <legend className="text-sm font-medium">What is it?</legend>
            <label className="flex min-h-11 items-center gap-2">
              <input
                type="radio"
                name="dataset"
                checked={dataset === 'grades'}
                onChange={() => {
                  setDataset('grades')
                  setSourceId('')
                }}
              />
              A reviewer’s grades (one reviewer per paste)
            </label>
            <label className="flex min-h-11 items-center gap-2">
              <input
                type="radio"
                name="dataset"
                checked={dataset === 'card-data'}
                onChange={() => {
                  setDataset('card-data')
                  setSourceId('')
                }}
              />
              17Lands card data (Table view, filters cleared, Ever in Hand and Not Seen ticked)
            </label>
          </fieldset>
          <label className="block text-sm font-medium">
            Source
            <select
              aria-label="Source"
              className={`${inputClass} mt-1`}
              value={sourceId}
              onChange={(e) => setSourceId(e.target.value)}
              required
            >
              <option value="">Choose…</option>
              {choices.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
              {dataset === 'grades' && <option value="own">The group’s own grades…</option>}
            </select>
          </label>
          {sourceId === 'own' && (
            <label className="block text-sm font-medium">
              Name for the group’s list (letters, digits, hyphens)
              <input className={`${inputClass} mt-1`} value={ownName} onChange={(e) => setOwnName(e.target.value)} required />
            </label>
          )}
          {dataset === 'card-data' && (
            <label className="block text-sm font-medium">
              Event type (must match the 17Lands page)
              <select
                aria-label="Event type"
                className={`${inputClass} mt-1`}
                value={eventType}
                onChange={(e) => setEventType(e.target.value)}
                required
              >
                <option value="">Choose…</option>
                {EVENT_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-sm font-medium">
              Copied on (default today)
              <input type="date" className={`${inputClass} mt-1`} value={copiedOn} onChange={(e) => setCopiedOn(e.target.value)} />
            </label>
            {dataset === 'grades' && (
              <label className="block text-sm font-medium">
                Published on (the review’s date)
                <input
                  type="date"
                  className={`${inputClass} mt-1`}
                  value={publishedOn}
                  onChange={(e) => setPublishedOn(e.target.value)}
                />
              </label>
            )}
          </div>
          <label className="block text-sm font-medium">
            Link to the source (optional; a label only, never opened by the app)
            <input type="url" className={`${inputClass} mt-1`} value={url} onChange={(e) => setUrl(e.target.value)} />
          </label>
          <label className="block text-sm font-medium">
            Upload the exported file
            <input aria-label="Upload the exported file" type="file" accept=".csv,.tsv,.txt,text/*" className="mt-1 block min-h-11 w-full text-sm" onChange={(e) => void readFile(e)} />
          </label>
          <label className="block text-sm font-medium">
            …or paste the text
            <textarea aria-label="Paste text" className={`${inputClass} mt-1 h-48 font-mono text-sm`} value={text} onChange={(e) => setText(e.target.value)} required />
          </label>
          <label className="flex min-h-11 items-center gap-2 text-sm">
            <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} />
            Replace today’s paste even if this one is much smaller
          </label>
          {result !== null && (
            <Notice tone={result.tone}>
              {result.lines.map((line, i) => (
                <p key={i}>{line}</p>
              ))}
            </Notice>
          )}
          <Button kind="primary" type="submit" disabled={busy || !text.trim() || !chosenSource}>
            {busy ? 'Checking…' : 'Store paste'}
          </Button>
        </form>
      </section>
      <section className="space-y-3">
        <h2 className="text-xl font-semibold">{setCode} pastes</h2>
        {pastes.length === 0 ? (
          <p className="text-sm text-slate-600">Nothing pasted for this set yet.</p>
        ) : (
          <ul className="space-y-2">
            {pastes.map((p) => (
              <li key={p.key} className="space-y-1 rounded-md border border-slate-200 bg-white p-3 text-sm" data-testid="paste">
                <p className="font-medium">{p.label}</p>
                <p className="text-slate-600">
                  {p.event_type ?? 'grades'} · copied {p.copied_on}
                  {p.published_on !== null && ` · published ${p.published_on}`} · pasted {p.import_day} (UTC) ·{' '}
                  {p.rows} rows
                  {p.replaced_at !== null && ` · replaced ${when(p.replaced_at)}`}
                </p>
                {mayDelete(p) && (
                  <Button kind="danger" onClick={() => void remove(p)}>
                    Delete
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
