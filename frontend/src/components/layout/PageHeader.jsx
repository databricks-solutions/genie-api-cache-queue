import { Link } from 'react-router-dom'

export default function PageHeader({ breadcrumbs = [], title, actions }) {
  return (
    <div className="px-6 py-4 bg-dbx-bg border-b border-dbx-border">
      {/* Breadcrumbs */}
      {breadcrumbs.length > 0 && (
        <div className="flex items-center gap-1.5 mb-1">
          {breadcrumbs.map((crumb, i) => (
            <span key={i} className="flex items-center gap-1.5">
              {i > 0 && <span className="text-[13px] text-dbx-text-secondary">&gt;</span>}
              {crumb.to ? (
                <Link to={crumb.to} className="text-[13px] text-dbx-text-link font-medium hover:underline">
                  {crumb.label}
                </Link>
              ) : (
                <span className="text-[13px] text-dbx-text font-medium">{crumb.label}</span>
              )}
            </span>
          ))}
        </div>
      )}

      {/* Title + Actions */}
      <div className="flex items-center justify-between">
        <h1 className="text-[22px] font-medium text-dbx-text">{title}</h1>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
    </div>
  )
}
