import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { api } from '../services/api'

// role: 'owner' | 'manage' | 'use'
// isOwner:  role === 'owner'
// isManage: role === 'manage' || role === 'owner'

const RoleContext = createContext({ role: 'use', isOwner: false, isManage: false, loading: true })

export function RoleProvider({ children }) {
  const [role, setRole] = useState('use')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.getMyRole()
      .then((data) => setRole(data.role || 'use'))
      .catch(() => setRole('use'))
      .finally(() => setLoading(false))
  }, [])

  const value = useMemo(() => ({
    role,
    loading,
    isOwner: role === 'owner',
    isManage: role === 'manage' || role === 'owner',
  }), [role, loading])

  return (
    <RoleContext.Provider value={value}>
      {children}
    </RoleContext.Provider>
  )
}

export function useRole() {
  return useContext(RoleContext)
}
