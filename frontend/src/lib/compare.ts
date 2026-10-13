// Compare tray: the selection lives in localStorage so it survives navigation. Per-viewer convenience only.
const KEY = 'byg.compare'
export const COMPARE_EVENT = 'byg:compare-changed'
export interface TrayItem { id: string; title: string }

export function getTray(): TrayItem[] {
  try { const v = JSON.parse(localStorage.getItem(KEY) ?? '[]'); return Array.isArray(v) ? v : [] } catch { return [] }
}
function save(items: TrayItem[]) {
  try { localStorage.setItem(KEY, JSON.stringify(items)) } catch { /* storage unavailable */ }
  window.dispatchEvent(new CustomEvent(COMPARE_EVENT))
}
export const MAX_COMPARE = 4
export function toggleTray(item: TrayItem): { ok: boolean; reason?: string } {
  const cur = getTray()
  if (cur.some((x) => x.id === item.id)) { save(cur.filter((x) => x.id !== item.id)); return { ok: true } }
  if (cur.length >= MAX_COMPARE) return { ok: false, reason: `You can compare up to ${MAX_COMPARE} events at once.` }
  save([...cur, item])
  return { ok: true }
}
export function removeFromTray(id: string) { save(getTray().filter((x) => x.id !== id)) }
export function clearTray() { save([]) }
