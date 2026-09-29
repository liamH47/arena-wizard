import { Link } from 'react-router'

import { request } from '../api/client'
import { useMe } from '../me-context'

// Attribution sits at the top of every page (17Lands' usage guidelines ask for a top-level
// credit). Until milestone 4 the web app uses no 17Lands public files: its numbers are
// 17Lands card data the group copied by hand, kept private (decisions 0005, 0008), so the
// credit says exactly that and claims no CC BY dataset.
export default function Header() {
  const me = useMe()
  const user = me?.user ?? null

  async function signOut() {
    await request('/auth/logout', { method: 'POST' })
    window.location.assign('/login')
  }

  return (
    <header className="border-b border-slate-200 bg-white">
      <div
        className="mx-auto max-w-5xl px-4 pt-2 text-xs text-slate-600"
        data-testid="attribution"
      >
        Stats:{' '}
        <a className="underline" href="https://www.17lands.com">
          17Lands
        </a>{' '}
        card data, hand-copied, private. Not affiliated with or endorsed by 17Lands (
        <a className="underline" href="https://www.17lands.com/usage_guidelines">
          usage guidelines
        </a>
        ).
      </div>
      <nav className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-4 gap-y-1 px-4 pb-2 text-sm">
        <Link className="flex min-h-11 items-center font-semibold" to="/">
          Arena Wizard
        </Link>
        <Link className="flex min-h-11 items-center underline-offset-4 hover:underline" to="/pastes">
          Pastes
        </Link>
        <Link className="flex min-h-11 items-center underline-offset-4 hover:underline" to="/runs">
          Results
        </Link>
        {me?.auth === 'google' && user !== null && (
          <span className="ml-auto flex items-center gap-2">
            <span className="hidden text-slate-600 sm:inline">{user.name || user.email}</span>
            <button
              type="button"
              className="min-h-11 px-2 underline-offset-4 hover:underline"
              onClick={() => void signOut()}
            >
              Sign out
            </button>
          </span>
        )}
      </nav>
    </header>
  )
}
