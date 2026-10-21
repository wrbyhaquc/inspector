import { useEffect, useState } from 'react'

/** useState that is remembered in this browser (localStorage). Falls back to the default if storage is unavailable. */
export function usePersistentState<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key)
      return raw !== null ? (JSON.parse(raw) as T) : initial
    } catch {
      return initial
    }
  })
  useEffect(() => {
    try { localStorage.setItem(key, JSON.stringify(value)) } catch { /* storage blocked: keep in memory only */ }
  }, [key, value])
  return [value, setValue] as const
}
