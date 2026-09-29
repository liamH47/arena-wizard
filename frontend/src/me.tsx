import { useCallback, useEffect, useState, type ReactNode } from 'react'

import { request } from './api/client'
import type { Me } from './api/types'
import { errorText } from './format'
import { MeContext } from './me-context'

export function MeProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let live = true
    request<Me>('/api/me')
      .then((found) => {
        if (live) setMe(found)
      })
      .catch((e: unknown) => {
        if (live) setError(errorText(e))
      })
    return () => {
      live = false
    }
  }, [attempt])

  const retry = useCallback(() => {
    setError(null)
    setAttempt((n) => n + 1)
  }, [])

  return <MeContext.Provider value={{ me, error, retry }}>{children}</MeContext.Provider>
}
