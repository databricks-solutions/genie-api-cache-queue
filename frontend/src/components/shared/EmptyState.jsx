export default function EmptyState({ icon: Icon, title, description, action }) {
  return (
    <div className="flex flex-col items-center justify-center py-20">
      {Icon && <Icon size={48} className="text-dbx-text-secondary mb-4" strokeWidth={1.5} />}
      <h3 className="text-[16px] font-medium text-dbx-text mb-1">{title}</h3>
      {description && (
        <p className="text-[13px] text-dbx-text-secondary mb-4 text-center max-w-sm">{description}</p>
      )}
      {action && <div>{action}</div>}
    </div>
  )
}
