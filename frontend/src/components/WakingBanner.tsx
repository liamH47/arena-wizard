import { useSyncExternalStore } from 'react'

import { isWaking, subscribeWaking } from '../api/client'

// Shown while any request is retrying: a free Render instance takes 30 to 60 s to wake,
// and the database a few seconds more. Sticky, so it stays in view wherever the player
// tapped from.
export default function WakingBanner() {
  const waking = useSyncExternalStore(subscribeWaking, isWaking)
  if (!waking) return null
  return (
    <div
      role="status"
      data-testid="waking-banner"
      className="sticky top-0 z-10 bg-amber-100 px-4 py-2 text-center text-sm text-amber-900"
    >
      Waking the server… keep this page open; it retries by itself. About 30 to 60 seconds.
    </div>
  )
}
