import { useState, useCallback } from 'react'

export default function DataTable({ columns, data, onRowClick, emptyMessage = 'No data' }) {
  const [colWidths, setColWidths] = useState({})

  const handleMouseDown = useCallback((e, colKey) => {
    e.preventDefault()
    const startX = e.clientX
    const th = e.target.closest('th')
    const startWidth = th.offsetWidth

    const handleMouseMove = (e) => {
      const diff = e.clientX - startX
      setColWidths(prev => ({ ...prev, [colKey]: Math.max(60, startWidth + diff) }))
    }

    const handleMouseUp = () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }, [])

  if (!data || data.length === 0) {
    return (
      <div className="text-center py-12 text-[13px] text-[#6F6F6F]">
        {emptyMessage}
      </div>
    )
  }

  return (
    <div className="w-full overflow-x-auto">
      <table className="w-full" style={{ tableLayout: 'fixed' }}>
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                className={`text-[13px] font-medium text-[#161616] bg-white ${col.align === 'center' ? 'text-center' : 'text-left'} relative`}
                style={{
                  padding: '4px 8px',
                  borderBottom: '1px solid #EBEBEB',
                  width: colWidths[col.key] ? `${colWidths[col.key]}px` : (col.width || 'auto'),
                  overflow: 'hidden',
                }}
              >
                {col.label}
                <div
                  onMouseDown={(e) => handleMouseDown(e, col.key)}
                  className="absolute top-0 right-0 bottom-0 w-1 cursor-col-resize hover:bg-[#2272B4]/30"
                />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row, rowIdx) => (
            <tr
              key={row.id || rowIdx}
              className={`hover:bg-[#F7F7F7] ${onRowClick ? 'cursor-pointer' : ''}`}
              onClick={() => onRowClick?.(row)}
            >
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={`text-[13px] text-[#161616] ${col.align === 'center' ? 'text-center' : ''}`}
                  style={{
                    padding: '8px',
                    borderBottom: '1px solid #EBEBEB',
                    verticalAlign: 'middle',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {col.render ? col.render(row[col.key], row) : row[col.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
