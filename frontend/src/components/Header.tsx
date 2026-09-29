// 17Lands asks that tools built on its data say so at the top level, with links, not in a
// footnote (https://www.17lands.com/usage_guidelines). The game files are CC BY 4.0, which
// also requires a license link and a statement of what was changed.
export default function Header() {
  return (
    <header className="border-b border-slate-200 bg-white px-4 py-2 text-sm text-slate-700">
      <p className="mx-auto max-w-3xl">
        Card statistics and color-pair data from{' '}
        <a className="underline" href="https://www.17lands.com/public_datasets">
          17Lands
        </a>{' '}
        public game files (
        <a className="underline" href="https://creativecommons.org/licenses/by/4.0/">
          CC BY 4.0
        </a>
        ), aggregated per day by Arena Wizard.
      </p>
    </header>
  )
}
