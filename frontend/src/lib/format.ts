import type { Fee } from '../api/types'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** Plain calendar dates (YYYY-MM-DD) are formatted without any timezone shift. */
export function fmtDate(d: string | null | undefined): string {
  if (!d) return 'Not stated'
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d)
  if (!m) return d
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}`
}

export function fmtDateRange(start: string | null, end: string | null): string {
  if (!start && !end) return 'Dates not stated'
  if (!end || end === start) return fmtDate(start)
  if (!start) return `Until ${fmtDate(end)}`
  const a = /^(\d{4})-(\d{2})-(\d{2})/.exec(start)
  const b = /^(\d{4})-(\d{2})-(\d{2})/.exec(end)
  if (a && b && a[1] === b[1] && a[2] === b[2]) return `${Number(a[3])}–${Number(b[3])} ${MONTHS[Number(a[2]) - 1]} ${a[1]}`
  return `${fmtDate(start)} – ${fmtDate(end)}`
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return 'Not stated'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'Asia/Kolkata' }).format(d) + ' IST'
}

export function fmtDeadline(iso: string | null | undefined): string {
  return iso ? fmtDateTime(iso) : 'No deadline stated'
}

export function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return 'never'
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return iso
  const mins = Math.round((Date.now() - t) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const h = Math.round(mins / 60)
  if (h < 48) return `${h} h ago`
  return `${Math.round(h / 24)} days ago`
}

export type FeeView = { text: string; tone: 'good' | 'unknown' | 'neutral'; uncertain: boolean; caveat: string | null }

/**
 * Fee display. "Not stated" is NEVER free: unknown fees keep an explicit uncertainty label,
 * and are only shown as free when the source stated so (status === 'free').
 */
export function feeView(fee: Fee | null | undefined): FeeView {
  if (!fee || fee.status === 'unknown') return { text: 'Fee not stated', tone: 'unknown', uncertain: true, caveat: 'Not stated is not the same as free' }
  if (fee.status === 'free') return { text: 'Free', tone: 'good', uncertain: false, caveat: 'Stated as free by the source' }
  if (fee.amount === null || fee.amount === undefined) return { text: 'Paid, amount not stated', tone: 'unknown', uncertain: true, caveat: 'The amount is unknown' }
  return { text: fee.label, tone: 'neutral', uncertain: false, caveat: null }
}

export function unknownIfEmpty(v: string | null | undefined, unknown = 'Not stated'): string {
  return v && v.trim() ? v : unknown
}

export function triState(v: boolean | null | undefined, yes: string, no: string): string {
  return v === true ? yes : v === false ? no : 'Not stated'
}

export function fmtPct(r: { numerator: number; denominator: number; pct: number | null }): string {
  return r.pct === null ? `${r.numerator} of ${r.denominator} (no data yet)` : `${r.pct}% (${r.numerator} of ${r.denominator})`
}

export function fmtBytes(n: number | null): string {
  if (n === null) return ''
  return n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`
}
