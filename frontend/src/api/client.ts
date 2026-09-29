// One way to talk to the backend. Render's free instance sleeps and Neon's database wakes
// slowly, so a request that fails with 503 or a network error is retried for up to a
// minute, and a banner tells the player the server is waking instead of leaving a blank
// page (docs/plan.md section 9, decision 0008).

const RETRY_FOR_MS = 60_000
const ATTEMPT_TIMEOUT_MS = 20_000
const SLOW_AFTER_MS = 3_000

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// ---- the "waking" banner: how many requests are slow or retrying right now --------------

let waking = 0
const listeners = new Set<() => void>()

function setWaking(delta: number): void {
  waking += delta
  for (const listener of listeners) listener()
}

export function subscribeWaking(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function isWaking(): boolean {
  return waking > 0
}

// ---- errors ------------------------------------------------------------------------------

type Detail = string | { msg?: string; loc?: (string | number)[] }[] | undefined

function detailText(detail: Detail): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const field = item.loc?.slice(1).join('.') ?? ''
        return field ? `${field}: ${item.msg ?? 'invalid'}` : (item.msg ?? 'invalid')
      })
      .join('; ')
  }
  return 'The request was refused.'
}

async function errorFor(response: Response): Promise<ApiError> {
  let body: { detail?: Detail; status?: string } = {}
  try {
    body = (await response.json()) as typeof body
  } catch {
    // Not JSON: fall through to a generic message.
  }
  if (response.status === 500 && body.status === 'database_error') {
    return new ApiError(500, 'The database is unavailable; tell the owner.')
  }
  if (response.status === 413) {
    return new ApiError(413, 'That is too large to send. Paste one set’s table at a time.')
  }
  if (response.status >= 500) {
    return new ApiError(response.status, 'The server had a problem. Try again in a minute.')
  }
  return new ApiError(response.status, detailText(body.detail))
}

function goToLogin(error?: string): void {
  if (window.location.pathname === '/login') return
  window.location.assign(error ? `/login?error=${error}` : '/login')
}

// ---- the request loop ----------------------------------------------------------------------

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function attempt(path: string, init: RequestInit): Promise<Response | null> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), ATTEMPT_TIMEOUT_MS)
  try {
    return await fetch(path, { ...init, credentials: 'same-origin', signal: controller.signal })
  } catch {
    return null
  } finally {
    clearTimeout(timer)
  }
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const started = Date.now()
  let slow = false
  const slowTimer = setTimeout(() => {
    slow = true
    setWaking(1)
  }, SLOW_AFTER_MS)
  let delay = 1_000
  try {
    for (;;) {
      const response = await attempt(path, { ...init, headers })
      const retryable = response === null || response.status === 503
      if (!retryable) {
        if (response.status === 401) {
          goToLogin()
          throw new ApiError(401, 'Please sign in.')
        }
        if (response.status === 403) {
          const error = await errorFor(response)
          if (error.message === 'not on the allow-list') goToLogin('denied')
          throw error
        }
        if (!response.ok) throw await errorFor(response)
        if (response.status === 204) return undefined as T
        return (await response.json()) as T
      }
      if (Date.now() - started + delay > RETRY_FOR_MS) {
        throw new ApiError(503, 'The server is still waking up. Try again in a minute.')
      }
      if (!slow) {
        slow = true
        setWaking(1)
      }
      await sleep(delay)
      delay = Math.min(delay * 2, 8_000)
    }
  } finally {
    clearTimeout(slowTimer)
    if (slow) setWaking(-1)
  }
}

export function jsonBody(value: unknown): RequestInit {
  return { body: JSON.stringify(value) }
}

export function newId(): string {
  return crypto.randomUUID()
}
