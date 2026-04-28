export default function RouterOverviewTab({ routerCfg }) {
  const members = routerCfg.members || []
  const activeMembers = members.filter((m) => !m.disabled)

  return (
    <div>
      <h2 className="text-[15px] font-medium text-dbx-text mb-3">Summary</h2>
      <div className="grid grid-cols-3 gap-4 mb-6">
        <StatCard label="Members" value={members.length} />
        <StatCard label="Active members" value={activeMembers.length} />
        <StatCard label="Decomposition" value={routerCfg.decompose_enabled ? 'On' : 'Off'} />
      </div>

      <h2 className="text-[15px] font-medium text-dbx-text mb-3">How this router works</h2>
      <div className="text-[13px] text-dbx-text-secondary space-y-2 max-w-2xl">
        <p>
          When a question comes in, the router embeds it and — if the routing cache is enabled —
          looks up the nearest prior decision within the similarity threshold
          ({routerCfg.similarity_threshold ?? 0.92}).
          On a cache miss, a selector LLM reads the member catalog ({activeMembers.length} active),
          picks the right member{routerCfg.decompose_enabled ? ' (or splits the question across several)' : ''},
          and the router dispatches each sub-question to its gateway in parallel.
        </p>
        <p>
          Use the <strong>Preview</strong> tab to see the routing decision for a question without
          spending warehouse time. Edit the <strong>when_to_use</strong> hints in the Members tab to
          tune routing accuracy.
        </p>
      </div>

      <h2 className="text-[15px] font-medium text-dbx-text mt-6 mb-3">Members</h2>
      {members.length === 0 ? (
        <p className="text-[13px] text-dbx-text-secondary">
          No members yet — go to the Members tab to add a gateway.
        </p>
      ) : (
        <div className="border border-dbx-border rounded overflow-hidden">
          <table className="w-full">
            <thead className="bg-dbx-bg-muted">
              <tr>
                <Th>Title</Th>
                <Th>Gateway ID</Th>
                <Th>When to use</Th>
                <Th align="center">Disabled</Th>
              </tr>
            </thead>
            <tbody>
              {members.map((m) => (
                <tr key={m.gateway_id} className="border-t border-dbx-border">
                  <Td><span className="font-medium">{m.title}</span></Td>
                  <Td><code className="text-[12px]">{m.gateway_id.slice(0, 12)}…</code></Td>
                  <Td>
                    <div className="text-[13px] text-dbx-text-secondary line-clamp-2 max-w-md">
                      {m.when_to_use}
                    </div>
                  </Td>
                  <Td align="center">
                    <span className={m.disabled ? 'text-dbx-text-danger' : 'text-dbx-text-secondary'}>
                      {m.disabled ? 'Yes' : '—'}
                    </span>
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function StatCard({ label, value }) {
  return (
    <div className="border border-dbx-border rounded px-4 py-3">
      <div className="text-[12px] text-dbx-text-secondary">{label}</div>
      <div className="text-[20px] font-medium text-dbx-text mt-1">{value}</div>
    </div>
  )
}

function Th({ children, align = 'left' }) {
  return (
    <th className={`text-${align} text-[12px] font-medium text-dbx-text-secondary px-3 py-2`}>{children}</th>
  )
}
function Td({ children, align = 'left' }) {
  return <td className={`text-${align} text-[13px] text-dbx-text px-3 py-2 align-top`}>{children}</td>
}
