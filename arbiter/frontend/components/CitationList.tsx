import type { Citation } from '@/lib/types'

const CLAUSE_COLORS: Record<string, string> = {
  RULE: 'bg-blue-50 text-blue-700 border-blue-200',
  EXCEPTION: 'bg-orange-50 text-orange-700 border-orange-200',
  OVERRIDE: 'bg-purple-50 text-purple-700 border-purple-200',
  WAIVER: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  RESTRICTION: 'bg-rose-50 text-rose-700 border-rose-200',
  PERMISSION: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  DEFINITION: 'bg-slate-100 text-slate-600 border-slate-200',
  PROCEDURE: 'bg-teal-50 text-teal-700 border-teal-200',
}

export default function CitationList({ citations }: { citations: Citation[] }) {
  if (!citations.length) return null
  return (
    <div className="mt-2 space-y-2">
      {citations.map((c, i) => (
        <div
          key={i}
          className="rounded-2xl border border-slate-200 bg-white/75 p-4 shadow-sm"
        >
          <div className="flex items-center gap-2 flex-wrap mb-2">
            {c.clause_type && (
              <span
                className={`text-xs px-2 py-0.5 rounded border font-mono ${
                  CLAUSE_COLORS[c.clause_type] ?? 'bg-slate-100 text-slate-600 border-slate-200'
                }`}
              >
                {c.clause_type}
              </span>
            )}
            <span className="text-xs font-mono text-slate-700">{c.policy_id}</span>
            {c.section_id && (
              <span className="text-xs text-slate-400">§{c.section_id}</span>
            )}
          </div>
          <p className="text-xs italic leading-relaxed text-slate-600">
            &ldquo;{c.text_excerpt}&rdquo;
          </p>
        </div>
      ))}
    </div>
  )
}
