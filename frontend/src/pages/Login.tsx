import { Navigate, useSearchParams } from 'react-router'

import { Notice } from '../components/ui'
import { useMe } from '../me-context'

// Why a sign-in came back here, in plain words (backend auth/routes.py).
const REASONS: Record<string, string> = {
  denied:
    'That Google account is not on the list for this private app. Ask the owner to add your email.',
  cancelled: 'Sign-in was cancelled. Try again when you are ready.',
  state: 'Sign-in took too long or started in another tab. Please try again.',
  google: 'Google could not complete the sign-in. Please try again in a moment.',
  warming: 'The server was still waking up. Please try signing in again.',
}

export default function Login() {
  const me = useMe()
  const [params] = useSearchParams()
  if (me?.auth === 'off' || (me !== null && me.user !== null)) return <Navigate to="/" replace />
  const reason = params.get('error')
  return (
    <section className="mx-auto max-w-md space-y-4 pt-8">
      <h1 className="text-2xl font-semibold">Arena Wizard</h1>
      <p className="text-slate-600">
        Best-of-One sealed deck recommendations for a private group of friends.
      </p>
      {reason !== null && <Notice tone="warn">{REASONS[reason] ?? 'Sign-in did not work. Please try again.'}</Notice>}
      <a
        href="/auth/google/login"
        className="flex min-h-11 items-center justify-center rounded-md bg-slate-900 px-4 py-2 font-medium text-white hover:bg-slate-700"
      >
        Sign in with Google
      </a>
    </section>
  )
}
