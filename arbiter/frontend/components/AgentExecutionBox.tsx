import type { AgentExecution } from '@/lib/types'

interface Props {
  executions: AgentExecution[]
}

export default function AgentExecutionBox({ executions }: Props) {
  if (executions.length === 0) return null

  return (
    <section className="glass-panel rounded-2xl border border-sky-100 p-4">
      <p className="eyebrow mb-3 text-sky-700">
        Execution details
      </p>
      <div className="space-y-2">
        {executions.map((execution, index) => (
          <div
            key={`${execution.agent}-${execution.provider}-${index}`}
            className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-xl bg-white/65 px-3 py-2 text-xs"
          >
            <span className="font-medium text-slate-800">{execution.agent}</span>
            <span className="text-slate-400">·</span>
            <span className="text-slate-500">{execution.outcome}</span>
            <span className="ml-auto rounded-lg bg-slate-100 px-2 py-1 font-mono text-[11px] text-sky-700">
              {execution.provider}
              {execution.model ? ` / ${execution.model}` : ''}
            </span>
            {execution.fallback_used && (
              <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700">
                FALLBACK
              </span>
            )}
            {execution.status === 'UNAVAILABLE' && (
              <span className="rounded bg-rose-100 px-1.5 py-0.5 text-[10px] font-semibold text-rose-700">
                UNAVAILABLE
              </span>
            )}
            {execution.calls > 1 && (
              <span className="text-[10px] text-slate-400">{execution.calls} calls</span>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}
