import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'

export interface AsyncState<T> {
  data: T | null
  error: ApiError | Error | null
  loading: boolean
  reload: () => void
  setData: (d: T | null) => void
}

/** Runs `fn` on mount and whenever `deps` change; stale responses are ignored. */
export function useAsync<T>(fn: (signal: AbortSignal) => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [loading, setLoading] = useState(true)
  const [tick, setTick] = useState(0)
  const fnRef = useRef(fn)
  fnRef.current = fn
  useEffect(() => {
    const ctrl = new AbortController()
    setLoading(true)
    setError(null)
    fnRef.current(ctrl.signal)
      .then((d) => { if (!ctrl.signal.aborted) { setData(d); setLoading(false) } })
      .catch((e) => { if (!ctrl.signal.aborted && (e as Error).name !== 'AbortError') { setError(e); setLoading(false) } })
    return () => ctrl.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])
  const reload = useCallback(() => setTick((t) => t + 1), [])
  return { data, error, loading, reload, setData }
}

export function useTitle(title: string) {
  useEffect(() => { document.title = `${title} · BeforeYouGo` }, [title])
}
