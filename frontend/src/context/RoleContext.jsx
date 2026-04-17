import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { api } from '../services/api'

// role: 'owner' | 'manage' | 'use'
// isOwner:  role === 'owner'
// isManage: role === 'manage' || role === 'owner'

const RoleContext = createContext({ role: 'use', identity: '', isOwner: false, isManage: false, loading: true, refreshRole: () => {} })

export function RoleProvider({ children }) {
  const [role, setRole] = useState('use')
  const [identity, setIdentity] = useState('')
  const [loading, setLoading] = useState(true)

  const fetchRole = useCallback(() => {
    api.getMyRole()
      .then((data) => {
        setRole(data.role || 'use')
        setIdentity(data.identity || '')
      })
      .catch(() => {
        setRole('use')
        setIdentity('')
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { fetchRole() }, [fetchRole])

  // Re-fetch when the tab regains focus (covers admin role changes mid-session)
  useEffect(() => {
    const onVisible = () => { if (document.visibilityState === 'visible') fetchRole() }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [fetchRole])

  const value = useMemo(() => ({
    role,
    identity,
    loading,
    isOwner: role === 'owner',
    isManage: role === 'manage' || role === 'owner',
    refreshRole: fetchRole,
  }), [role, identity, loading, fetchRole])

  return (
    <RoleContext.Provider value={value}>
      {children}
    </RoleContext.Provider>
  )
}

export function useRole() {
  return useContext(RoleContext)
}
