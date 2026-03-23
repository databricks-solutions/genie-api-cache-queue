export default function DataTable({ columns, data, onRowClick, emptyMessage = 'No data' }) {
  if (!data || data.length === 0) {
    return (
      <div className="text-center py-12 text-[13px] text-[#6F6F6F]">
        {emptyMessage}
      </div>
    )
  }

  return (
    <div className="w-full overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                className="text-left text-[13px] font-medium text-[#161616] bg-white px-2 py-1"
                style={{
                  padding: '4px 8px',
                  borderBottom: '1px solid #EBEBEB',
                  width: col.width || 'auto',
                }}
              >
                {col.label}
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
                  className="text-[13px] text-[#161616]"
                  style={{
                    padding: '8px',
                    borderBottom: '1px solid #EBEBEB',
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
