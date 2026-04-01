import { NavLink } from 'react-router-dom'
import { Layers, Play, Code2, Plug, Bug } from 'lucide-react'

const mainNavItems = [
  { to: '/', icon: Layers, label: 'Gateways', end: true },
  { to: '/playground', icon: Play, label: 'Playground' },
]

const bottomNavItems = [
  { to: '/api-reference', icon: Code2, label: 'API Reference' },
  { to: '/mcp', icon: Plug, label: 'MCP' },
  { to: '/debug', icon: Bug, label: 'Debug' },
]

function NavItem({ to, icon: Icon, label, end }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        `flex items-center gap-2 px-3 py-1.5 rounded text-[13px] transition-colors ${
          isActive
            ? 'bg-dbx-blue-hover text-dbx-text-link'
            : 'text-dbx-text hover:bg-dbx-neutral-hover'
        }`
      }
    >
      {({ isActive }) => (
        <>
          <Icon size={16} className={isActive ? 'text-dbx-text-link' : 'text-dbx-text-secondary'} />
          <span>{label}</span>
        </>
      )}
    </NavLink>
  )
}

export default function Sidebar() {
  return (
    <aside className="w-[200px] bg-dbx-sidebar flex flex-col p-2 h-full">
      <nav className="flex flex-col gap-0.5 flex-1">
        {mainNavItems.map((item) => (
          <NavItem key={item.to} {...item} />
        ))}

        <div className="flex-1" />

        <div className="text-[11px] text-dbx-text-secondary tracking-wider px-3 mb-1">Tools</div>
        {bottomNavItems.map((item) => (
          <NavItem key={item.to} {...item} />
        ))}
      </nav>
    </aside>
  )
}
