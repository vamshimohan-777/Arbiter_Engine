import type { Ruling, RulingDecision } from '@/lib/types'

interface Props {
  ruling: Ruling
}

const CONFIGS: Record<RulingDecision, { label: string; bgClass: string; borderClass: string; iconBg: string; icon: string; textClass: string }> = {
  PERMITTED: {
    label: 'PERMITTED',
    bgClass: 'bg-emerald-50/85',
    borderClass: 'border-emerald-200',
    iconBg: 'bg-emerald-500',
    icon: '✓',
    textClass: 'text-emerald-950',
  },
  NOT_PERMITTED: {
    label: 'NOT PERMITTED',
    bgClass: 'bg-rose-50/90',
    borderClass: 'border-rose-200',
    iconBg: 'bg-rose-500',
    icon: '✗',
    textClass: 'text-rose-950',
  },
  NEEDS_CLARIFICATION: {
    label: 'NEEDS CLARIFICATION',
    bgClass: 'bg-amber-50/90',
    borderClass: 'border-amber-200',
    iconBg: 'bg-amber-500',
    icon: '?',
    textClass: 'text-amber-950',
  },
  SERVICE_UNAVAILABLE: {
    label: 'SERVICE UNAVAILABLE',
    bgClass: 'bg-slate-50/90',
    borderClass: 'border-slate-300',
    iconBg: 'bg-slate-500',
    icon: '!',
    textClass: 'text-slate-800',
  },
}

/** Parse "1. SUPERSESSION: text. 2. SCOPE: text." into labelled steps */
function parseSteps(text: string): { label: string; body: string }[] | null {
  const pattern = /\d+\.\s+([A-Z ]+?):\s+/g
  // `Array.from` is compatible with this project's ES5 TypeScript target;
  // spreading RegExpStringIterator requires `downlevelIteration` instead.
  const matches = Array.from(text.matchAll(pattern))
  if (matches.length < 2) return null

  const steps: { label: string; body: string }[] = []
  for (let i = 0; i < matches.length; i++) {
    const m = matches[i]
    const start = (m.index ?? 0) + m[0].length
    const end = matches[i + 1]?.index ?? text.length
    steps.push({ label: m[1].trim(), body: text.slice(start, end).trim() })
  }
  return steps
}

export default function VerdictCard({ ruling }: Props) {
  const cfg = CONFIGS[ruling.decision] ?? CONFIGS.NEEDS_CLARIFICATION
  const steps = parseSteps(ruling.explanation)

  return (
    <div className={`rounded-[26px] border ${cfg.bgClass} ${cfg.borderClass} overflow-hidden shadow-[0_14px_30px_rgba(50,74,115,0.08)]`}>
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-slate-900/10 px-5 py-4">
        <span className={`w-7 h-7 rounded-full ${cfg.iconBg} flex items-center justify-center text-white font-bold text-sm`}>
          {cfg.icon}
        </span>
        <span className={`font-bold tracking-wider text-sm ${cfg.textClass}`}>{cfg.label}</span>
        <span className="ml-auto text-xs text-slate-500">
          {Math.round(ruling.confidence * 100)}% confidence
        </span>
      </div>

      {/* Explanation */}
      <div className="px-5 py-4 space-y-3">
        {steps ? (
          steps.map((s) => (
            <div key={s.label}>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-500">
                {s.label}
              </p>
              <p className={`text-sm leading-relaxed ${cfg.textClass} opacity-90`}>{s.body}</p>
            </div>
          ))
        ) : (
          <p className={`text-sm leading-relaxed ${cfg.textClass} opacity-90`}>
            {ruling.explanation}
          </p>
        )}
      </div>

      {/* Blocking clause */}
      {ruling.blocking_clause && (
        <div className="mx-5 mb-4 rounded-2xl border border-slate-900/10 bg-white/50 p-3">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
            Blocking Clause
          </p>
          <p className={`text-sm italic ${cfg.textClass} opacity-85 leading-snug`}>
            &ldquo;{ruling.blocking_clause.text}&rdquo;
          </p>
          <p className="mt-1.5 text-xs font-mono text-slate-500">
            {ruling.blocking_clause.policy_id}
            {ruling.blocking_clause.section_id
              ? ` § ${ruling.blocking_clause.section_id}`
              : ''}
          </p>
        </div>
      )}

      {/* Relevant relationships */}
      {ruling.caveats && ruling.caveats.length > 0 && (
        <div className="px-5 pb-4">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-500">
            Policy Chain
          </p>
          <ul className="space-y-0.5">
            {ruling.caveats.map((c, i) => (
              <li key={i} className="flex gap-2 text-xs text-slate-600">
                <span className="text-slate-400">›</span>
                <span>{c}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
