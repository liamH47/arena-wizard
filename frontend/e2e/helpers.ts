import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import type { APIRequestContext } from '@playwright/test'

// Made-up data only: a pool of real FRA card names and numbers, and a random grade list.
const FIXTURES = join(import.meta.dirname, 'fixtures')
export const POOL_TEXT = readFileSync(join(FIXTURES, 'fra-pool.txt'), 'utf-8')
export const GRADES_PATH = join(FIXTURES, 'fra-grades.csv')
export const GRADES_TEXT = readFileSync(GRADES_PATH, 'utf-8')

type Paste = { key: string; set_code: string }

export async function clearPastes(api: APIRequestContext): Promise<void> {
  const listed = await api.get('/api/pastes?set_code=FRA')
  for (const paste of (await listed.json()) as Paste[]) {
    await api.delete(`/api/pastes/${paste.set_code}/${paste.key}`)
  }
}

export async function pasteGrades(api: APIRequestContext): Promise<void> {
  const response = await api.post('/api/pastes', {
    data: { set_code: 'FRA', dataset: 'grades', source_id: 'llu-marc', text: GRADES_TEXT },
  })
  if (![200, 201].includes(response.status())) {
    throw new Error(`pasting grades failed: ${response.status()} ${await response.text()}`)
  }
}

export async function builtPool(api: APIRequestContext): Promise<string> {
  const id = crypto.randomUUID()
  const created = await api.post('/api/pools', {
    data: { id, set_code: 'FRA', format: 'bo1_sealed', export_text: POOL_TEXT },
  })
  if (created.status() !== 201) throw new Error(`creating a pool failed: ${created.status()}`)
  await pasteGrades(api)
  await api.post(`/api/pools/${id}/builds`)
  return id
}
