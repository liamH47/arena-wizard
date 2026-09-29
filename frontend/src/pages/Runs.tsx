import { useEffect, useState } from 'react'

import { ApiError, jsonBody, request } from '../api/client'
import type { Run } from '../api/types'
import { Button, Notice } from '../components/ui'
import { errorText, when } from '../format'

function RunRow({ run, onChange, onGone }: { run: Run; onChange: (r: Run) => void; onGone: () => void }) {
  const [error, setError] = useState<string | null>(null)

  async function patch(fields: Partial<Pick<Run, 'wins' | 'losses'>>) {
    setError(null)
    try {
      onChange(await request<Run>(`/api/runs/${run.id}`, { method: 'PATCH', ...jsonBody(fields) }))
    } catch (e) {
      setError(errorText(e))
    }
  }

  async function remove() {
    setError(null)
    try {
      await request(`/api/runs/${run.id}`, { method: 'DELETE' })
      onGone()
    } catch (e) {
      // A retried delete finds nothing to delete: that is success.
      if (e instanceof ApiError && e.status === 404) onGone()
      else setError(errorText(e))
    }
  }

  return (
    <li className="space-y-2 rounded-md border border-slate-200 bg-white p-3" data-testid="run">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-lg font-semibold tabular-nums" data-testid="record">
          {run.wins}-{run.losses}
        </span>
        <span className="text-sm text-slate-600">
          {run.event_name || 'Unnamed event'} · build {run.build_id}, deck {run.deck_index + 1} ·{' '}
          {when(run.created_at)}
        </span>
      </div>
      {run.notes && <p className="text-sm text-slate-700">{run.notes}</p>}
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => void patch({ wins: Math.min(20, run.wins + 1) })}>+1 win</Button>
        <Button onClick={() => void patch({ losses: Math.min(20, run.losses + 1) })}>+1 loss</Button>
        <Button onClick={() => void patch({ wins: Math.max(0, run.wins - 1) })}>−1 win</Button>
        <Button onClick={() => void patch({ losses: Math.max(0, run.losses - 1) })}>−1 loss</Button>
        <Button kind="danger" onClick={() => void remove()}>
          Delete
        </Button>
      </div>
      {error !== null && <Notice tone="error">{error}</Notice>}
    </li>
  )
}

export default function Runs() {
  const [runs, setRuns] = useState<Run[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    request<Run[]>('/api/runs')
      .then(setRuns)
      .catch((e: unknown) => setError(errorText(e)))
  }, [])

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Results</h1>
      {error !== null && <Notice tone="error">{error}</Notice>}
      {runs !== null && runs.length === 0 && (
        <p className="text-sm text-slate-600">No results yet. Record one from a deck page.</p>
      )}
      <ul className="space-y-3">
        {(runs ?? []).map((run) => (
          <RunRow
            key={run.id}
            run={run}
            onChange={(updated) => setRuns((all) => (all ?? []).map((r) => (r.id === updated.id ? updated : r)))}
            onGone={() => setRuns((all) => (all ?? []).filter((r) => r.id !== run.id))}
          />
        ))}
      </ul>
    </div>
  )
}
