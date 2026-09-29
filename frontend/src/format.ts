// Small helpers shared by the pages.

export function when(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong.'
}

export const inputClass =
  'min-h-11 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-base text-slate-900'
