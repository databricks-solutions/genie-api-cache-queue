export default function StatusBadge({ status }) {
  const isActive = status === 'active'

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-3 py-0.5 rounded text-[13px] ${
        isActive ? 'bg-[#F3FCF6] text-[#161616]' : 'bg-gray-100 text-[#6F6F6F]'
      }`}
    >
      <span
        className={`w-2 h-2 rounded-full ${isActive ? 'bg-green-500' : 'bg-gray-400'}`}
      />
      {isActive ? 'Active' : 'Paused'}
    </span>
  )
}
