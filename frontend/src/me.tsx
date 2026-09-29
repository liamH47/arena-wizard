import { useEffect, useState, type ReactNode } from 'react'

import { request } from './api/client'
import type { Me } from './api/types'
import { MeContext } from './me-context'

export function MeProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  useEffect(() => {
    request<Me>('/api/me')
      .then(setMe)
      .catch(() => setMe({ auth: 'google', user: null }))
  }, [])
  return <MeContext.Provider value={me}>{children}</MeContext.Provider>
}
