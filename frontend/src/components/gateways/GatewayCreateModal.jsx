import { useState, useEffect, useMemo } from 'react'
import { Search, Loader2 } from 'lucide-react'
import { api } from '../../services/api'
import Modal from '../shared/Modal'

function SelectionTable({ columns, data, selectedId, onSelect, loading, error, onManualFallback }) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 size={18} className="animate-spin text-[#6F6F6F]" />
        <span className="ml-2 text-[13px] text-[#6F6F6F]">Loading...</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="text-center py-6">
        <p className="text-[13px] text-[#6F6F6F] mb-2">{error}</p>
        {onManualFallback && (
          <button
            onClick={onManualFallback}
            className="text-[13px] text-[#0E538B] hover:underline"
          >
            Enter ID manually
          </button>
        )}
      </div>
    )
  }

  if (!data || data.length === 0) {
    return (
      <div className="text-center py-6">
        <p className="text-[13px] text-[#6F6F6F]">No results found</p>
        {onManualFallback && (
          <button
            onClick={onManualFallback}
            className="text-[13px] text-[#0E538B] hover:underline mt-1"
          >
            Enter ID manually
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="border border-[#EBEBEB] rounded max-h-[200px] overflow-auto">
      <table className="w-full">
        <thead className="sticky top-0 bg-white">
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                className="text-left text-[13px] font-medium text-[#161616]"
                style={{ padding: '4px 8px', borderBottom: '1px solid #EBEBEB' }}
              >
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row) => {
            const isSelected = selectedId === row.id
            return (
              <tr
                key={row.id}
                className={`cursor-pointer transition-colors ${
                  isSelected
                    ? 'bg-[rgba(34,114,180,0.08)]'
                    : 'hover:bg-[#F7F7F7]'
                }`}
                onClick={() => onSelect(isSelected ? null : row.id)}
              >
                {columns.map((col) => (
                  <td
                    key={col.key}
                    className="text-[13px] text-[#161616]"
                    style={{ padding: '6px 8px', borderBottom: '1px solid #EBEBEB' }}
                  >
                    {col.render ? col.render(row[col.key], row) : row[col.key] || '-'}
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export default function GatewayCreateModal({ open, onClose, onCreated }) {
  const [name, setName] = useState('')
  const [spaceSearch, setSpaceSearch] = useState('')
  const [selectedSpace, setSelectedSpace] = useState(null)

  const [spaces, setSpaces] = useState([])
  const [spacesLoading, setSpacesLoading] = useState(false)
  const [spacesError, setSpacesError] = useState(null)
  const [manualSpaceId, setManualSpaceId] = useState('')
  const [showManualSpace, setShowManualSpace] = useState(false)

  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState(null)

  useEffect(() => {
    if (!open) return
    // Reset state on open
    setName('')
    setSelectedSpace(null)
    setSpaceSearch('')
    setManualSpaceId('')
    setShowManualSpace(false)
    setCreateError(null)

    // Fetch spaces
    setSpacesLoading(true)
    setSpacesError(null)
    api.listGenieSpaces()
      .then((data) => {
        const raw = Array.isArray(data) ? data : data.spaces || []
        // Normalize: API returns space_id/title, we need id/name
        const normalized = raw.map((s) => ({
          id: s.space_id || s.id,
          name: s.title || s.name || s.space_id || s.id,
          description: s.description || '',
          warehouse_id: s.warehouse_id || '',
        }))
        setSpaces(normalized)
      })
      .catch((err) => {
        setSpacesError(err.response?.data?.detail || 'Failed to load Genie spaces')
      })
      .finally(() => setSpacesLoading(false))
  }, [open])

  const filteredSpaces = useMemo(() => {
    if (!spaceSearch) return spaces
    const q = spaceSearch.toLowerCase()
    return spaces.filter(
      (s) =>
        (s.name || '').toLowerCase().includes(q) ||
        (s.id || '').toLowerCase().includes(q)
    )
  }, [spaces, spaceSearch])

  const selectedSpaceObj = spaces.find(s => s.id === selectedSpace)
  const resolvedSpaceId = showManualSpace ? manualSpaceId.trim() : selectedSpace
  const canCreate = name.trim() && resolvedSpaceId && !creating

  const handleCreate = async () => {
    if (!canCreate) return
    setCreating(true)
    setCreateError(null)
    try {
      const payload = {
        name: name.trim(),
        genie_space_id: resolvedSpaceId,
      }
      // If the space has a warehouse_id, include it
      if (selectedSpaceObj?.warehouse_id) {
        payload.sql_warehouse_id = selectedSpaceObj.warehouse_id
      }
      const result = await api.createGateway(payload)
      onCreated?.(result)
    } catch (err) {
      setCreateError(err.response?.data?.detail || err.message || 'Failed to create gateway')
    } finally {
      setCreating(false)
    }
  }

  const spaceColumns = [
    { key: 'name', label: 'Name' },
    {
      key: 'id',
      label: 'Space ID',
      render: (val) => (
        <span className="text-[12px] font-mono text-[#6F6F6F]">{val}</span>
      ),
    },
  ]

  return (
    <Modal isOpen={open} onClose={onClose} title="Create Gateway" maxWidth="max-w-2xl">
      {/* Section 1: Gateway name */}
      <div className="mb-6">
        <label className="block text-[13px] font-medium text-[#161616] mb-1">
          Configure gateway name
        </label>
        <p className="text-[13px] text-[#6F6F6F] mb-2">
          Gateway name cannot be changed after creation.
        </p>
        <input
          type="text"
          placeholder="Enter gateway name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full h-8 px-3 border border-[#CBCBCB] rounded text-[13px] text-[#161616] placeholder:text-[#6F6F6F] focus:outline-none focus:border-[#2272B4]"
        />
      </div>

      {/* Section 2: Select Genie Space */}
      <div className="mb-6">
        <label className="block text-[13px] font-medium text-[#161616] mb-2">
          Select Genie Space
        </label>

        {showManualSpace ? (
          <div>
            <input
              type="text"
              placeholder="Enter Genie Space ID"
              value={manualSpaceId}
              onChange={(e) => setManualSpaceId(e.target.value)}
              className="w-full h-8 px-3 border border-[#CBCBCB] rounded text-[13px] text-[#161616] placeholder:text-[#6F6F6F] focus:outline-none focus:border-[#2272B4] font-mono"
            />
            <button
              onClick={() => { setShowManualSpace(false); setManualSpaceId('') }}
              className="text-[13px] text-[#0E538B] hover:underline mt-1"
            >
              Back to list
            </button>
          </div>
        ) : (
          <>
            {!spacesLoading && !spacesError && spaces.length > 0 && (
              <div className="relative mb-2">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#6F6F6F]" />
                <input
                  type="text"
                  placeholder="Search by name"
                  value={spaceSearch}
                  onChange={(e) => setSpaceSearch(e.target.value)}
                  className="w-full h-8 pl-8 pr-3 border border-[#CBCBCB] rounded text-[13px] text-[#161616] placeholder:text-[#6F6F6F] focus:outline-none focus:border-[#2272B4]"
                />
              </div>
            )}
            <SelectionTable
              columns={spaceColumns}
              data={filteredSpaces}
              selectedId={selectedSpace}
              onSelect={setSelectedSpace}
              loading={spacesLoading}
              error={spacesError}
              onManualFallback={() => setShowManualSpace(true)}
            />
          </>
        )}

        {/* Show selected space info */}
        {selectedSpaceObj && (
          <div className="mt-2 text-[12px] text-[#6F6F6F]">
            {selectedSpaceObj.description && <span>{selectedSpaceObj.description} · </span>}
            Warehouse: <span className="font-mono">{selectedSpaceObj.warehouse_id || 'not set'}</span>
          </div>
        )}
      </div>

      {/* Error */}
      {createError && (
        <p className="text-[13px] text-red-600 mb-3">{createError}</p>
      )}

      {/* Footer */}
      <div className="flex items-center justify-end gap-2 pt-2 border-t border-[#EBEBEB]">
        <button
          onClick={onClose}
          className="h-8 px-3 border border-[#CBCBCB] rounded text-[13px] text-[#161616] bg-transparent hover:bg-[#F7F7F7] transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={handleCreate}
          disabled={!canCreate}
          className={`h-8 px-3 rounded text-[13px] text-white transition-colors flex items-center gap-1.5 ${
            canCreate
              ? 'bg-[#2272B4] hover:bg-[#1b5e96]'
              : 'bg-[#D8D8D8] cursor-not-allowed'
          }`}
        >
          {creating && <Loader2 size={14} className="animate-spin" />}
          Create
        </button>
      </div>
    </Modal>
  )
}
