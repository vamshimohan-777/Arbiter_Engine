import type { Citation } from '@/lib/types'

const CLAUSE_COLORS: Record<string, string> = {
  RULE: 'bg-blue-900 text-blue-200 border-blue-700',
  EXCEPTION: 'bg-orange-900 text-orange-200 border-orange-700',
  OVERRIDE: 'bg-purple-900 text-purple-200 border-purple-700',
  WAIVER: 'bg-green-900 text-green-200 border-green-700',
  RESTRICTION: 'bg-red-900 text-red-200 border-red-700',
  PERMISSION: 'bg-emerald-900 text-emerald-200 border-emerald-700',
  DEFINITION: 'bg-neutral-800 text-neutral-300 border-neutral-600',
  PROCEDURE: 'bg-teal-900 text-teal-200 border-teal-700',
}

export default function CitationList({ citations }: { citations: Citation[] }) {
  if (!citations.length) return null
  return (
    <div className="mt-2 space-y-2">
      {citations.map((c, i) => (
        <div
          key={i}
          className="rounded-lg bg-neutral-900 border border-neutral-800 p-3"
        >
          <div className="flex items-center gap-2 flex-wrap mb-2">
            {c.clause_type && (
              <span
                className={`text-xs px-2 py-0.5 rounded border font-mono ${
                  CLAUSE_COLORS[c.clause_type] ?? 'bg-neutral-800 text-neutral-300 border-neutral-600'
                }`}
              >
                {c.clause_type}
              </span>
            )}
            <span className="text-xs text-neutral-400 font-mono">{c.policy_id}</span>
            {c.section_id && (
              <span className="text-xs text-neutral-600">§{c.section_id}</span>
            )}
          </div>
          <p className="text-xs text-neutral-300 italic">
            &ldquo;{c.text_excerpt}&rdquo;
          </p>
        </div>
      ))}
    </div>
  )
}
