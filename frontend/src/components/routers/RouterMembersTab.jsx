import { useEffect, useState } from 'react'
import { Plus, Trash2, Save, X } from 'lucide-react'
import { api } from '../../services/api'
import Modal from '../shared/Modal'
import { useRole } from '../../context/RoleContext'

export default function RouterMembersTab({ routerCfg, onChange }) {
  const { isManage } = useRole()
  const [editingId, setEditingId] = useState(null)
  const [showAdd, setShowAdd] = useState(false)
  const members = routerCfg.members || []

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-[15px] font-medium text-dbx-text">Members</h2>
          <p className="text-[13px] text-dbx-text-secondary">
            Each member is a gateway plus a <code className="text-[12px]">when_to_use</code> hint the selector LLM reads.
            Good hints include both "use for…" and "NOT for…" clauses.
          </p>
        </div>
        {isManage && (
          <button
            onClick={() => setShowAdd(true)}
            className="flex items-center gap-2 bg-dbx-blue text-white rounded h-8 px-3 text-[13px] font-medium hover:bg-dbx-blue-dark transition-colors"
          >
            <Plus size={14} />
            Add member
          </button>
        )}
      </div>

      {members.length === 0 ? (
        <div className="border border-dbx-border rounded px-4 py-10 text-center text-[13px] text-dbx-text-secondary">
          No members yet. Add a gateway to start routing.
        </div>
      ) : (
        <div className="space-y-3">
          {members.map((m) => (
            <MemberCard
              key={m.gateway_id}
              member={m}
              routerId={routerCfg.id}
              isEditing={editingId === m.gateway_id}
              canEdit={isManage}
              onBeginEdit={() => setEditingId(m.gateway_id)}
              onCancelEdit={() => setEditingId(null)}
              onChange={() => { setEditingId(null); onChange?.() }}
            />
          ))}
        </div>
      )}

      {isManage && (
        <AddMemberModal
          open={showAdd}
          onClose={() => setShowAdd(false)}
          routerId={routerCfg.id}
          existingMemberIds={members.map((m) => m.gateway_id)}
          onAdded={() => { setShowAdd(false); onChange?.() }}
        />
      )}
    </div>
  )
}

function MemberCard({ member, routerId, isEditing, canEdit, onBeginEdit, onCancelEdit, onChange }) {
  const [title, setTitle] = useState(member.title)
  const [whenToUse, setWhenToUse] = useState(member.when_to_use)
  const [tables, setTables] = useState((member.tables || []).join('\n'))
  const [samples, setSamples] = useState((member.sample_questions || []).join('\n'))
  const [disabled, setDisabled] = useState(!!member.disabled)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    if (isEditing) {
      setTitle(member.title)
      setWhenToUse(member.when_to_use)
      setTables((member.tables || []).join('\n'))
      setSamples((member.sample_questions || []).join('\n'))
      setDisabled(!!member.disabled)
      setError(null)
    }
  }, [isEditing, member])

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      await api.updateRouterMember(routerId, member.gateway_id, {
        title,
        when_to_use: whenToUse,
        tables: tables.split('\n').map((s) => s.trim()).filter(Boolean),
        sample_questions: samples.split('\n').map((s) => s.trim()).filter(Boolean),
        disabled,
      })
      onChange?.()
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const del = async () => {
    if (!window.confirm(`Remove ${member.title} from this router?`)) return
    setDeleting(true)
    try {
      await api.deleteRouterMember(routerId, member.gateway_id)
      onChange?.()
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Delete failed')
    } finally {
      setDeleting(false)
    }
  }

  if (!isEditing) {
    return (
      <div className="border border-dbx-border rounded px-4 py-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 mb-1">
              <span className="font-medium text-[13px] text-dbx-text">{member.title}</span>
              {member.disabled && (
                <span className="text-[11px] px-1.5 py-0.5 rounded bg-dbx-status-red-bg text-dbx-text-danger">
                  Disabled
                </span>
              )}
            </div>
            <div className="text-[12px] text-dbx-text-secondary mb-2">
              <code>{member.gateway_id}</code>
            </div>
            <div className="text-[13px] text-dbx-text whitespace-pre-wrap">{member.when_to_use}</div>
            {(member.tables?.length > 0) && (
              <div className="text-[12px] text-dbx-text-secondary mt-2">
                <span className="font-medium">Tables: </span>{member.tables.join(', ')}
              </div>
            )}
            {(member.sample_questions?.length > 0) && (
              <div className="text-[12px] text-dbx-text-secondary mt-1">
                <span className="font-medium">Sample questions: </span>{member.sample_questions.length}
              </div>
            )}
          </div>
          {canEdit && (
            <div className="flex items-center gap-2">
              <button
                onClick={onBeginEdit}
                className="h-7 px-2 text-[12px] text-dbx-text border border-dbx-border-input rounded hover:bg-dbx-neutral-hover"
              >Edit</button>
              <button
                onClick={del}
                disabled={deleting}
                className="h-7 w-7 flex items-center justify-center text-dbx-text-secondary hover:text-dbx-text-danger disabled:opacity-50"
                title="Remove member"
              >
                <Trash2 size={14} />
              </button>
            </div>
          )}
        </div>
        {error && (
          <div className="mt-2 px-3 py-2 rounded bg-red-50 border border-red-200 text-red-700 text-[12px]">
            {error}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="border border-dbx-blue rounded px-4 py-3 bg-dbx-blue-hover/40">
      <div className="text-[12px] text-dbx-text-secondary mb-1">
        Gateway: <code>{member.gateway_id}</code>
      </div>
      <Field label="Title">
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className="w-full h-8 px-2 border border-dbx-border-input rounded text-[13px] bg-dbx-bg"
        />
      </Field>
      <Field label="when_to_use (the selector LLM reads this)">
        <textarea
          value={whenToUse}
          onChange={(e) => setWhenToUse(e.target.value)}
          rows={5}
          className="w-full px-2 py-1.5 border border-dbx-border-input rounded text-[13px] bg-dbx-bg resize-y font-mono"
        />
      </Field>
      <Field label="Tables (one per line, optional)">
        <textarea
          value={tables}
          onChange={(e) => setTables(e.target.value)}
          rows={3}
          className="w-full px-2 py-1.5 border border-dbx-border-input rounded text-[12px] bg-dbx-bg resize-y font-mono"
        />
      </Field>
      <Field label="Sample questions (one per line, optional)">
        <textarea
          value={samples}
          onChange={(e) => setSamples(e.target.value)}
          rows={3}
          className="w-full px-2 py-1.5 border border-dbx-border-input rounded text-[12px] bg-dbx-bg resize-y"
        />
      </Field>
      <label className="flex items-center gap-2 text-[13px] text-dbx-text mt-2">
        <input type="checkbox" checked={disabled} onChange={(e) => setDisabled(e.target.checked)} />
        Disabled (hide from selector without removing)
      </label>
      {error && (
        <div className="mt-2 px-3 py-2 rounded bg-red-50 border border-red-200 text-red-700 text-[12px]">
          {error}
        </div>
      )}
      <div className="flex items-center gap-2 mt-3">
        <button
          onClick={save}
          disabled={saving}
          className="flex items-center gap-1.5 h-8 px-3 text-[13px] font-medium text-white bg-dbx-blue rounded hover:bg-dbx-blue-dark disabled:opacity-50"
        >
          <Save size={13} />
          {saving ? 'Saving...' : 'Save'}
        </button>
        <button
          onClick={onCancelEdit}
          disabled={saving}
          className="flex items-center gap-1.5 h-8 px-3 text-[13px] font-medium text-dbx-text border border-dbx-border-input rounded hover:bg-dbx-neutral-hover disabled:opacity-50"
        >
          <X size={13} />
          Cancel
        </button>
      </div>
    </div>
  )
}

function AddMemberModal({ open, onClose, routerId, existingMemberIds, onAdded }) {
  const [gateways, setGateways] = useState([])
  const [loading, setLoading] = useState(false)
  const [gatewayId, setGatewayId] = useState('')
  const [title, setTitle] = useState('')
  const [whenToUse, setWhenToUse] = useState('')
  const [tables, setTables] = useState('')
  const [samples, setSamples] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!open) return
    setLoading(true)
    api.listGateways()
      .then((data) => setGateways(Array.isArray(data) ? data : []))
      .catch(() => setGateways([]))
      .finally(() => setLoading(false))
    setGatewayId(''); setTitle(''); setWhenToUse(''); setTables(''); setSamples(''); setError(null)
  }, [open])

  const available = gateways.filter((g) => !existingMemberIds.includes(g.id))
  const selectedGw = gateways.find((g) => g.id === gatewayId)

  const submit = async () => {
    if (!gatewayId) { setError('Pick a gateway'); return }
    if (!whenToUse.trim()) { setError('when_to_use is required'); return }
    setSubmitting(true)
    setError(null)
    try {
      await api.addRouterMember(routerId, {
        gateway_id: gatewayId,
        title: title.trim() || undefined,
        when_to_use: whenToUse,
        tables: tables.split('\n').map((s) => s.trim()).filter(Boolean),
        sample_questions: samples.split('\n').map((s) => s.trim()).filter(Boolean),
      })
      onAdded?.()
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to add member')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal isOpen={open} onClose={submitting ? () => {} : onClose} title="Add router member" maxWidth="max-w-xl">
      <div className="pt-2 max-h-[70vh] overflow-auto">
        <Field label="Gateway">
          {loading ? (
            <div className="text-[13px] text-dbx-text-secondary">Loading gateways…</div>
          ) : available.length === 0 ? (
            <div className="text-[13px] text-dbx-text-secondary">
              No gateways available to add. Create a gateway first or remove an existing member.
            </div>
          ) : (
            <select
              value={gatewayId}
              onChange={(e) => {
                setGatewayId(e.target.value)
                const gw = gateways.find((g) => g.id === e.target.value)
                if (gw && !title) setTitle(gw.name)
              }}
              className="w-full h-8 px-2 border border-dbx-border-input rounded text-[13px] bg-dbx-bg"
            >
              <option value="">— pick one —</option>
              {available.map((g) => (
                <option key={g.id} value={g.id}>{g.name} — {g.genie_space_id?.slice(0, 12)}…</option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Title (defaults to the gateway name)">
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={selectedGw?.name || ''}
            className="w-full h-8 px-2 border border-dbx-border-input rounded text-[13px] bg-dbx-bg"
          />
        </Field>
        <Field label="when_to_use">
          <textarea
            value={whenToUse}
            onChange={(e) => setWhenToUse(e.target.value)}
            placeholder="Use for …  NOT for: …"
            rows={5}
            className="w-full px-2 py-1.5 border border-dbx-border-input rounded text-[13px] bg-dbx-bg resize-y font-mono"
          />
        </Field>
        <Field label="Tables (one per line, optional)">
          <textarea
            value={tables}
            onChange={(e) => setTables(e.target.value)}
            rows={3}
            className="w-full px-2 py-1.5 border border-dbx-border-input rounded text-[12px] bg-dbx-bg resize-y font-mono"
          />
        </Field>
        <Field label="Sample questions (one per line, optional)">
          <textarea
            value={samples}
            onChange={(e) => setSamples(e.target.value)}
            rows={3}
            className="w-full px-2 py-1.5 border border-dbx-border-input rounded text-[12px] bg-dbx-bg resize-y"
          />
        </Field>
        {error && (
          <div className="px-3 py-2 rounded bg-red-50 border border-red-200 text-red-700 text-[12px] mt-2">
            {error}
          </div>
        )}
        <div className="flex gap-3 mt-4">
          <button
            onClick={onClose}
            disabled={submitting}
            className="flex-1 h-8 text-[13px] font-medium text-dbx-text border border-dbx-border-input rounded hover:bg-dbx-neutral-hover disabled:opacity-50"
          >Cancel</button>
          <button
            onClick={submit}
            disabled={submitting || !gatewayId || !whenToUse.trim()}
            className="flex-1 h-8 text-[13px] font-medium text-white bg-dbx-blue rounded hover:bg-dbx-blue-dark disabled:opacity-50"
          >{submitting ? 'Adding...' : 'Add member'}</button>
        </div>
      </div>
    </Modal>
  )
}

function Field({ label, children }) {
  return (
    <div className="mb-3">
      <label className="block text-[12px] font-medium text-dbx-text-secondary mb-1">{label}</label>
      {children}
    </div>
  )
}
