import { Link } from 'react-router-dom'

export default function PageHeader({ breadcrumbs = [], title, actions }) {
  return (
    <div className="px-6 py-4 bg-white border-b border-[#EBEBEB]">
      {/* Breadcrumbs */}
      {breadcrumbs.length > 0 && (
        <div className="flex items-center gap-1.5 mb-1">
          {breadcrumbs.map((crumb, i) => (
            <span key={i} className="flex items-center gap-1.5">
              {i > 0 && <span className="text-[13px] text-[#6F6F6F]">&gt;</span>}
              {crumb.to ? (
                <Link to={crumb.to} className="text-[13px] text-[#0E538B] font-medium hover:underline">
                  {crumb.label}
                </Link>
              ) : (
                <span className="text-[13px] text-[#161616] font-medium">{crumb.label}</span>
              )}
            </span>
          ))}
        </div>
      )}

      {/* Title + Actions */}
      <div className="flex items-center justify-between">
        <h1 className="text-[22px] font-medium text-[#161616]">{title}</h1>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
    </div>
  )
}
