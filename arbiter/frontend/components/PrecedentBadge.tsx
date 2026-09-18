import type { PrecedentResult } from '@/lib/types'

export default function PrecedentBadge({
  precedent,
}: {
  precedent: PrecedentResult
}) {
  if (precedent.status === 'CHECK_UNAVAILABLE') {
    return (
      <div className="flex items-start gap-2 px-3 py-2 bg-amber-950 border border-amber-800 rounded-lg">
        <span className="mt-0.5 text-amber-400">⚠</span>
        <div>
          <span className="text-xs font-semibold text-amber-300">Precedent check unavailable</span>
          <p className="text-xs text-amber-200/80 mt-0.5">
            The ruling was completed, but historical consistency could not be verified.
          </p>
        </div>
      </div>
    )
  }

  if (precedent.status === 'NO_RELEVANT_PRECEDENT' || !precedent.has_precedent) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 bg-neutral-900 border border-neutral-700 rounded-lg">
        <span className="text-neutral-500">○</span>
        <span className="text-xs text-neutral-400">No prior precedent</span>
      </div>
    )
  }

  const isConsistent = precedent.status === 'CONSISTENT'
  return (
    <div
      className={`flex items-start gap-2 px-3 py-2 rounded-lg border ${
        isConsistent
          ? 'bg-neutral-900 border-neutral-700'
          : 'bg-red-950 border-red-700'
      }`}
    >
      <span className="mt-0.5">{isConsistent ? '🔁' : '⚡'}</span>
      <div>
        <span
          className={`text-xs font-semibold ${
            isConsistent ? 'text-neutral-300' : 'text-red-300'
          }`}
        >
          {isConsistent ? 'Consistent with precedent' : 'Inconsistent with precedent'}
        </span>
        {isConsistent && precedent.consistency_explanation && (
          <p className="text-xs text-neutral-500 mt-0.5">
            {precedent.consistency_explanation}
          </p>
        )}
        {!isConsistent && precedent.discrepancy_explanation && (
          <p className="text-xs text-red-200 mt-0.5">
            {precedent.discrepancy_explanation}
          </p>
        )}
      </div>
    </div>
  )
}
