import type { Query } from '../api/client'

export interface Filters {
  q: string
  category: string[]
  format: string[]
  topics: string[]
  city: string
  country: string
  date_from: string
  date_to: string
  deadline_from: string
  deadline_to: string
  max_fee: string
  free_only: boolean
  include_unknown_cost: boolean
  certificate: boolean
  mentorship: boolean
  beginner: boolean
  has_prize: boolean
  accessibility_documented: boolean
  cross_college: boolean
  source: string
  origin_type: string
  require_known: string[]
  include_past: boolean
  sort: 'relevance' | 'date' | 'deadline'
  page: number
}

export const EMPTY_FILTERS: Filters = {
  q: '', category: [], format: [], topics: [], city: '', country: '', date_from: '', date_to: '', deadline_from: '', deadline_to: '',
  max_fee: '', free_only: false, include_unknown_cost: false, certificate: false, mentorship: false, beginner: false, has_prize: false,
  accessibility_documented: false, cross_college: false, source: '', origin_type: '', require_known: [], include_past: false, sort: 'relevance', page: 1,
}

const BOOLS = ['free_only', 'include_unknown_cost', 'certificate', 'mentorship', 'beginner', 'has_prize', 'accessibility_documented', 'cross_college', 'include_past'] as const
const LISTS = ['category', 'format', 'topics', 'require_known'] as const
const STRS = ['q', 'city', 'country', 'date_from', 'date_to', 'deadline_from', 'deadline_to', 'max_fee', 'source', 'origin_type'] as const

export function paramsToFilters(p: URLSearchParams): Filters {
  const f: Filters = { ...EMPTY_FILTERS, category: [], format: [], topics: [], require_known: [] }
  for (const k of STRS) f[k] = p.get(k) ?? ''
  for (const k of BOOLS) f[k] = p.get(k) === 'true'
  for (const k of LISTS) f[k] = p.getAll(k)
  const s = p.get('sort')
  f.sort = s === 'date' || s === 'deadline' ? s : 'relevance'
  const pg = Number(p.get('page'))
  f.page = Number.isInteger(pg) && pg > 0 ? pg : 1
  return f
}

/** Query sent to GET /api/events (and mirrored into the page URL). Empty / false values are omitted. */
export function filtersToQuery(f: Filters): Query {
  const q: Query = {}
  for (const k of STRS) if (f[k].trim()) q[k] = f[k].trim()
  for (const k of BOOLS) if (f[k]) q[k] = true
  for (const k of LISTS) if (f[k].length) q[k] = f[k]
  if (f.sort !== 'relevance') q.sort = f.sort
  if (f.page > 1) q.page = f.page
  return q
}

export function filtersToSearchParams(f: Filters): URLSearchParams {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(filtersToQuery(f))) {
    if (Array.isArray(v)) v.forEach((x) => p.append(k, String(x)))
    else p.set(k, String(v))
  }
  return p
}

export const FILTER_LABELS: Record<string, string> = {
  q: 'Search', city: 'City', country: 'Country', date_from: 'From', date_to: 'Until', deadline_from: 'Deadline from', deadline_to: 'Deadline until',
  max_fee: 'Max fee (INR)', free_only: 'Stated as free', include_unknown_cost: 'Includes unstated fees', certificate: 'Certificate', mentorship: 'Mentorship',
  beginner: 'Beginner-friendly', has_prize: 'Has prize', accessibility_documented: 'Accessibility documented', cross_college: 'Cross-college teams',
  source: 'Source', origin_type: 'Origin', include_past: 'Includes past events',
}

export const REQUIRE_KNOWN_OPTIONS = [
  { value: 'fee', label: 'Fee stated' }, { value: 'deadline', label: 'Deadline stated' }, { value: 'eligibility', label: 'Eligibility stated' },
  { value: 'venue', label: 'Venue stated' }, { value: 'schedule', label: 'Schedule stated' }, { value: 'contact', label: 'Contact stated' },
]
