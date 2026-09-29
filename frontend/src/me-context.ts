import { createContext, useContext } from 'react'

import type { Me } from './api/types'

// Who is signed in, read from /api/me, which always answers 200 so the login page can ask
// without a redirect loop. `me` is null until it has answered. `error` is set when it could
// not answer at all (the server is still waking): that is not "signed out", so pages show
// a waking notice with Try again instead of sending the player to the login page.
export type MeState = {
  me: Me | null
  error: string | null
  retry: () => void
}

export const MeContext = createContext<MeState>({ me: null, error: null, retry: () => {} })

export function useMe(): Me | null {
  return useContext(MeContext).me
}

export function useMeState(): MeState {
  return useContext(MeContext)
}
