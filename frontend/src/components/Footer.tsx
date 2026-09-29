// The notice text is the one the Wizards Fan Content Policy asks for, verbatim.
export default function Footer() {
  return (
    <footer className="border-t border-slate-200 bg-white px-4 py-4 text-xs text-slate-500">
      <div className="mx-auto max-w-3xl space-y-1">
        <p>
          Arena Wizard is unofficial Fan Content permitted under the{' '}
          <a className="underline" href="https://company.wizards.com/en/legal/fancontentpolicy">
            Fan Content Policy
          </a>
          . Not approved/endorsed by Wizards. Portions of the materials used are property of
          Wizards of the Coast. ©Wizards of the Coast LLC.
        </p>
        <p>
          Card data and images from{' '}
          <a className="underline" href="https://scryfall.com">
            Scryfall
          </a>
          . Not affiliated with or endorsed by 17Lands or Scryfall.
        </p>
      </div>
    </footer>
  )
}
