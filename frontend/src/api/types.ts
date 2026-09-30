// Shapes of the JSON the backend returns (backend/src/arena_wizard/api/*.py).

export type User = {
  user_id: string
  email: string
  name: string
  picture: string
}

export type Me = {
  auth: 'off' | 'google'
  user: User | null
  // May delete any friend's paste (decision 0008); always true with auth off.
  owner: boolean
}

export type SetInfo = {
  code: string
  name: string
  arena_release_date: string
  embargo_until: string
  formats: string[]
  usual_range: [number, number]
}

export type PoolSummary = {
  id: string
  set_code: string
  format: string
  created_at: string
  updated_at: string
}

export type PoolListItem = PoolSummary & {
  has_build: boolean
  // The export's first card line, so pools of one set can be told apart.
  hint: string
}

export type PoolEntry = {
  name: string
  count: number
  set_code: string
  collector_number: string
  rarity: string
  colors: string
  mana_cost: string
  type_line: string
  image_uri: string | null
}

export type PoolWarning = {
  kind: string
  message: string
  line_no: number | null
  raw: string
  suggestions: string[]
}

export type Pool = PoolSummary & {
  export_text: string
  nonbasic_count: number
  usual_range: [number, number]
  entries: PoolEntry[]
  basics: { name: string; count: number }[]
  warnings: PoolWarning[]
}

export type Term = { name: string; contribution: number; detail: string }

export type CardValue = {
  name: string
  q: number
  se: number
  basis: string
  observed: number | null
  games: number
  source: string
  layers: { name: string; share: number }[]
  grades: { source: string; grade: string }[]
  adjustment: { q_delta: number; by: string } | null
}

export type Deck = {
  deck_index: number
  label: string
  colors: string
  splash: string | null
  total: number
  total_se: number
  gap_to_next: number | null
  gap_se: number | null
  toss_up: boolean
  explanations: string[]
  terms: Term[]
  spells: {
    name: string
    count: number
    mana_cost: string
    mana_value: number
    type_line: string
    rarity: string
    image_uri: string | null
  }[]
  lands: { name: string; count: number }[]
  values: CardValue[]
  arena_list: string
}

export type Build = {
  id: number
  current: boolean
  pool_id: string
  set_code: string
  mode: string
  config_version: string
  created_at: string
  data_lines: string[]
  refusal: string | null
  decks: Deck[]
}

export type Run = {
  id: string
  build_id: number
  deck_index: number
  wins: number
  losses: number
  event_name: string
  notes: string
  created_at: string
  updated_at: string
}

export type PasteSource = { id: string; label: string; dataset: string }

export type Paste = {
  key: string
  set_code: string
  dataset: string
  event_type: string | null
  source_id: string
  label: string
  import_day: string
  copied_on: string
  published_on: string | null
  rows: number
  pasted_by: string
  replaced_at: string | null
}

export type PasteResult = { messages: string[] }

export type Adjustment = {
  name: string
  bomb: 'add' | 'remove' | null
  q_delta: number | null
  note: string
  by: string
  updated_at: string
}
