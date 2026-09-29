import type { ButtonHTMLAttributes, ReactNode } from 'react'

// Shared pieces: buttons with 44 px tap targets, and notices.

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { kind?: 'primary' | 'plain' | 'danger' }

const KINDS = {
  primary: 'bg-slate-900 text-white hover:bg-slate-700 disabled:bg-slate-400',
  plain: 'border border-slate-300 bg-white text-slate-900 hover:bg-slate-100 disabled:text-slate-400',
  danger: 'border border-red-300 bg-white text-red-700 hover:bg-red-50 disabled:text-red-300',
} as const

export function Button({ kind = 'plain', className = '', ...props }: ButtonProps) {
  return (
    <button
      type="button"
      className={`min-h-11 rounded-md px-4 py-2 text-sm font-medium ${KINDS[kind]} ${className}`}
      {...props}
    />
  )
}

export function Notice({
  tone = 'info',
  children,
}: {
  tone?: 'info' | 'warn' | 'error' | 'ok'
  children: ReactNode
}) {
  const colors = {
    info: 'border-sky-200 bg-sky-50 text-sky-900',
    warn: 'border-amber-300 bg-amber-50 text-amber-900',
    error: 'border-red-300 bg-red-50 text-red-900',
    ok: 'border-emerald-300 bg-emerald-50 text-emerald-900',
  }[tone]
  return (
    <div role={tone === 'error' ? 'alert' : 'status'} className={`rounded-md border p-3 text-sm ${colors}`}>
      {children}
    </div>
  )
}

// A page that could not load: say why, and offer the retry the player would otherwise do
// by reloading.
export function LoadError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <Notice tone="error">
      <p>{message}</p>
      <Button className="mt-2" onClick={onRetry}>
        Try again
      </Button>
    </Notice>
  )
}
