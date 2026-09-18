import type { SimulationResult } from '@/lib/types'

const DECISION_COLORS: Record<string, string> = {
  NOT_PERMITTED: 'text-red-400',
  PERMITTED: 'text-green-400',
  NEEDS_CLARIFICATION: 'text-yellow-400',
}

export default function SimulationReport({
  result,
}: {
  result: SimulationResult
}) {
  const unavailable = result.status === 'CHECK_UNAVAILABLE'
  const noEligibleCases = result.status === 'NO_ELIGIBLE_CASES'
  const change = result.change
  const actionDescription = change.description?.trim() || 'Unspecified hypothetical policy change'
  return (
    <div className="rounded-xl border border-blue-800 bg-neutral-900 p-5">
      <div className="flex items-center gap-2 mb-4">
        <span className="text-blue-400">⚡</span>
        <h3 className="text-sm font-bold text-blue-300">
          Simulation Impact Report
        </h3>
      </div>

      {/* The proposed action is request data, so it remains visible even if
          a fallback provider cannot complete the optional impact analysis. */}
      <div className="mb-4 rounded-lg border border-neutral-700 bg-neutral-800 p-3">
        <p className="text-xs font-semibold uppercase tracking-wider text-neutral-400">
          Proposed policy action
        </p>
        <p className="mt-1 text-sm leading-relaxed text-neutral-100">{actionDescription}</p>
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-neutral-500">
          <span>Type: {change.change_type.replaceAll('_', ' ').toLowerCase()}</span>
          {change.target_policy_id && <span>Policy: {change.target_policy_id}</span>}
          {change.target_section_id && <span>Section: {change.target_section_id}</span>}
        </div>
        {change.new_text && (
          <p className="mt-2 border-l-2 border-blue-700 pl-2 text-xs leading-relaxed text-blue-200">
            Proposed rule text: {change.new_text}
          </p>
        )}
      </div>

      {/* Summary banner */}
      <div className="mb-4 bg-blue-950 border border-blue-900 rounded-lg p-3">
        <p className="text-xs text-blue-200 leading-relaxed">{result.impact_summary}</p>
      </div>

      {unavailable && (
        <p className="mb-4 text-xs text-amber-300">
          ⚠ Simulation service unavailable — no impact conclusion was reached.
        </p>
      )}
      {noEligibleCases && (
        <p className="mb-4 text-xs text-neutral-400">
          No eligible precedent cases were found; this is not an impact conclusion.
        </p>
      )}

      {/* Stats */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        <div className="bg-neutral-800 rounded-lg p-3 text-center">
          <p className="text-2xl font-bold text-blue-400">{result.total_questions_tested}</p>
          <p className="text-xs text-neutral-500 mt-1">tested</p>
        </div>
        <div className="bg-neutral-800 rounded-lg p-3 text-center">
          <p className="text-2xl font-bold text-amber-400">{result.total_affected}</p>
          <p className="text-xs text-neutral-500 mt-1">affected</p>
        </div>
        <div className="bg-neutral-800 rounded-lg p-3 text-center">
          <p className="text-2xl font-bold text-neutral-400">
            {result.unaffected_impacts.length}
          </p>
          <p className="text-xs text-neutral-500 mt-1">unchanged</p>
        </div>
      </div>

      {/* Flipped rulings */}
      {result.flipped_impacts.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-neutral-400 uppercase tracking-wider mb-3">
            Changed rulings
          </p>
          <div className="space-y-2">
            {result.flipped_impacts.map((impact, i) => (
              <div
                key={i}
                className="bg-neutral-800 border border-neutral-700 rounded-lg p-3"
              >
                <p className="text-xs text-neutral-200 mb-2 leading-relaxed">
                  {impact.question}
                </p>
                <div className="flex items-center gap-2">
                  <span
                    className={`text-xs font-mono ${
                      DECISION_COLORS[impact.original_decision] ?? 'text-neutral-400'
                    }`}
                  >
                    {impact.original_decision}
                  </span>
                  <span className="text-neutral-600 text-xs">→</span>
                  <span
                    className={`text-xs font-mono ${
                      DECISION_COLORS[impact.hypothetical_decision] ?? 'text-neutral-400'
                    }`}
                  >
                    {impact.hypothetical_decision}
                  </span>
                </div>
                {impact.hypothetical_explanation && (
                  <p className="text-xs text-neutral-500 mt-1 leading-relaxed">
                    {impact.hypothetical_explanation.slice(0, 200)}
                    {impact.hypothetical_explanation.length > 200 ? '…' : ''}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
