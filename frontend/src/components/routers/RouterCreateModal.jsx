import { useState } from 'react'
import { api } from '../../services/api'
import Modal from '../shared/Modal'

export default function RouterCreateModal({ open, onClose, onCreated }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  const reset = () => { setName(''); setDescription(''); setError(null) }
  const handleClose = () => { if (!submitting) { reset(); onClose?.() } }

  const submit = async () => {
    if (!name.trim()) { setError('Name is required'); return }
    setSubmitting(true)
    setError(null)
    try {
      const body = { name: name.trim(), description: description.trim() }
      const created = await api.createRouter(body)
      reset()
      onCreated?.(created)
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to create router')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal isOpen={open} onClose={handleClose} title="Create router" maxWidth="max-w-lg">
      <div className="pt-2">
        <p className="text-[13px] text-dbx-text-secondary mb-4">
          A router groups several gateways under a catalog and dispatches incoming questions to the right member. You'll add gateways as members after creating the router.
        </p>
        <label className="block text-[13px] font-medium text-dbx-text mb-1">Name</label>
        <input
          type="text"
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. operations-router"
          className="w-full h-9 px-3 border border-dbx-border-input rounded text-[13px] text-dbx-text focus:outline-none focus:border-dbx-blue bg-dbx-bg mb-4"
        />
        <label className="block text-[13px] font-medium text-dbx-text mb-1">Description (optional)</label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="What kind of questions does this router handle?"
          rows={3}
          className="w-full px-3 py-2 border border-dbx-border-input rounded text-[13px] text-dbx-text focus:outline-none focus:border-dbx-blue bg-dbx-bg resize-none"
        />
        {error && (
          <div className="mt-3 px-3 py-2 rounded bg-red-50 border border-red-200 text-red-700 text-[12px]">
            {error}
          </div>
        )}
        <div className="flex gap-3 mt-5">
          <button
            onClick={handleClose}
            disabled={submitting}
            className="flex-1 h-8 text-[13px] font-medium text-dbx-text border border-dbx-border-input rounded hover:bg-dbx-neutral-hover transition-colors disabled:opacity-50"
          >Cancel</button>
          <button
            onClick={submit}
            disabled={submitting || !name.trim()}
            className="flex-1 h-8 text-[13px] font-medium text-white bg-dbx-blue rounded hover:bg-dbx-blue-dark transition-colors disabled:opacity-50"
          >{submitting ? 'Creating...' : 'Create'}</button>
        </div>
      </div>
    </Modal>
  )
}
