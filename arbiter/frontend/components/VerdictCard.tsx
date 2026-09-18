import type { Ruling, RulingDecision } from '@/lib/types'

interface Props {
  ruling: Ruling
}

const CONFIGS: Record<RulingDecision, { label: string; bgClass: string; borderClass: string; iconBg: string; icon: string; textClass: string }> = {
  PERMITTED: {
    label: 'PERMITTED',
    bgClass: 'bg-green-950',
    borderClass: 'border-green-800',
    iconBg: 'bg-green-700',
    icon: '✓',
    textClass: 'text-green-100',
  },
  NOT_PERMITTED: {
    label: 'NOT PERMITTED',
    bgClass: 'bg-red-950',
    borderClass: 'border-red-900',
    iconBg: 'bg-red-700',
    icon: '✗',
    textClass: 'text-red-100',
  },
  NEEDS_CLARIFICATION: {
    label: 'NEEDS CLARIFICATION',
    bgClass: 'bg-yellow-950',
    borderClass: 'border-yellow-800',
    iconBg: 'bg-yellow-700',
    icon: '?',
    textClass: 'text-yellow-100',
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
    <div className={`rounded-xl border ${cfg.bgClass} ${cfg.borderClass} overflow-hidden`}>
      {/* Header */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-white/10">
        <span className={`w-7 h-7 rounded-full ${cfg.iconBg} flex items-center justify-center text-white font-bold text-sm`}>
          {cfg.icon}
        </span>
        <span className={`font-bold tracking-wider text-sm ${cfg.textClass}`}>{cfg.label}</span>
        <span className="ml-auto text-xs opacity-50">
          {Math.round(ruling.confidence * 100)}% confidence
        </span>
      </div>

      {/* Explanation */}
      <div className="px-5 py-4 space-y-3">
        {steps ? (
          steps.map((s) => (
            <div key={s.label}>
              <p className="text-xs font-semibold uppercase tracking-wider opacity-50 mb-1">
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
        <div className="mx-5 mb-4 rounded-lg bg-black/20 border border-white/10 p-3">
          <p className="text-xs font-semibold uppercase tracking-wider opacity-50 mb-2">
            Blocking Clause
          </p>
          <p className={`text-sm italic ${cfg.textClass} opacity-85 leading-snug`}>
            &ldquo;{ruling.blocking_clause.text}&rdquo;
          </p>
          <p className="text-xs opacity-40 mt-1.5 font-mono">
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
          <p className="text-xs opacity-40 font-semibold uppercase tracking-wider mb-1">
            Policy Chain
          </p>
          <ul className="space-y-0.5">
            {ruling.caveats.map((c, i) => (
              <li key={i} className="text-xs opacity-60 flex gap-2">
                <span className="opacity-40">›</span>
                <span>{c}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
