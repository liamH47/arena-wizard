import { createContext, useContext } from 'react'

import type { Me } from './api/types'

// Who is signed in, read once from /api/me, which always answers 200 so the login page can
// ask without a redirect loop. Null until it has answered.
export const MeContext = createContext<Me | null>(null)

export function useMe(): Me | null {
  return useContext(MeContext)
}
