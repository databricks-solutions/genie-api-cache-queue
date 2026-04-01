export default function StatusBadge({ status }) {
  const isActive = status === 'active'

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-3 py-0.5 rounded text-[13px] ${
        isActive ? 'bg-dbx-status-green-bg text-dbx-text' : 'bg-dbx-sidebar text-dbx-text-secondary'
      }`}
    >
      <span
        className={`w-2 h-2 rounded-full ${isActive ? 'bg-green-500' : 'bg-gray-400'}`}
      />
      {isActive ? 'Active' : 'Paused'}
    </span>
  )
}
