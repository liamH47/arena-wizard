import { useSyncExternalStore } from 'react'

import { isWaking, subscribeWaking } from '../api/client'

// Shown while any request is slow or retrying: a free Render instance takes 30 to 60 s to
// wake, and the database a few seconds more.
export default function WakingBanner() {
  const waking = useSyncExternalStore(subscribeWaking, isWaking)
  if (!waking) return null
  return (
    <div role="status" className="bg-amber-100 px-4 py-2 text-center text-sm text-amber-900">
      Waking the server and database… this can take up to a minute.
    </div>
  )
}
