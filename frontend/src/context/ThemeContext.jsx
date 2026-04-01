import { createContext, useContext, useEffect, useState, useRef } from 'react'
import { api } from '../services/api'

// themeMode: 'light' | 'dark' | 'system'
// effectiveTheme: 'light' | 'dark'  (resolved value used to apply the CSS class)

const ThemeContext = createContext(null)

function getOsTheme() {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function applyTheme(resolved) {
  document.documentElement.classList.toggle('dark', resolved === 'dark')
}

export function ThemeProvider({ children }) {
  const [themeMode, setThemeMode] = useState(() => {
    return localStorage.getItem('themeMode') || 'system'
  })

  // effectiveTheme starts from localStorage/OS so the first render is already correct
  const [effectiveTheme, setEffectiveTheme] = useState(() => {
    const mode = localStorage.getItem('themeMode') || 'system'
    if (mode !== 'system') return mode
    return getOsTheme()
  })

  // Track workspace API state:
  //   undefined = not yet fetched (initial / after themeMode change)
  //   null      = fetched, API returned no answer
  //   'light'|'dark' = fetched, definitive answer
  const workspaceThemeRef = useRef(undefined)

  // Whenever themeMode changes, re-resolve and persist
  useEffect(() => {
    localStorage.setItem('themeMode', themeMode)

    if (themeMode === 'light' || themeMode === 'dark') {
      workspaceThemeRef.current = undefined
      setEffectiveTheme(themeMode)
      applyTheme(themeMode)
      return
    }

    // system mode: try workspace API first, fall back to OS
    let cancelled = false
    workspaceThemeRef.current = undefined  // reset: "not yet fetched"

    api.getWorkspaceAppearance()
      .then(({ theme }) => {
        if (cancelled) return
        workspaceThemeRef.current = theme // null means "API didn't know"
        const resolved = theme ?? getOsTheme()
        setEffectiveTheme(resolved)
        applyTheme(resolved)
      })
      .catch(() => {
        if (cancelled) return
        workspaceThemeRef.current = null
      })

    // Apply OS immediately while waiting for API
    const osResolved = getOsTheme()
    setEffectiveTheme(osResolved)
    applyTheme(osResolved)

    return () => {
      cancelled = true
      workspaceThemeRef.current = undefined
    }
  }, [themeMode])

  // When in system mode, also listen for OS changes as fallback
  useEffect(() => {
    if (themeMode !== 'system') return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = (e) => {
      // Only apply OS change if the API has responded AND returned no answer (null).
      // undefined = still in flight (API will overwrite); 'light'/'dark' = API owns it.
      if (workspaceThemeRef.current === null) {
        const resolved = e.matches ? 'dark' : 'light'
        setEffectiveTheme(resolved)
        applyTheme(resolved)
      }
    }
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [themeMode])

  return (
    <ThemeContext.Provider value={{ themeMode, setThemeMode, effectiveTheme }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme() {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used within a ThemeProvider')
  return ctx
}
