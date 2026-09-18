import type { SensitivityResult } from '@/lib/types'

export default function SensitivityBadge({
  sensitivity,
}: {
  sensitivity: SensitivityResult
}) {
  if (sensitivity.status === 'CHECK_UNAVAILABLE') {
    return (
      <div className="flex items-start gap-2 px-3 py-2 bg-amber-950 border border-amber-800 rounded-lg">
        <span className="text-amber-400">⚠</span>
        <div>
          <span className="text-xs font-semibold text-amber-300">Sensitivity check unavailable</span>
          <p className="text-xs text-amber-200/80 mt-0.5">The ruling was not assessed for nearby decision flips.</p>
        </div>
      </div>
    )
  }

  if (!sensitivity.is_fragile) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 bg-neutral-900 border border-neutral-700 rounded-lg">
        <span className="text-green-400">🛡</span>
        <div>
          <span className="text-xs font-semibold text-neutral-300">Stable ruling</span>
          <p className="text-xs text-neutral-500 mt-0.5">{sensitivity.summary}</p>
        </div>
      </div>
    )
  }

  const flip = sensitivity.nearest_flip
  return (
    <div className="flex items-start gap-2 px-3 py-2 bg-amber-950 border border-amber-700 rounded-lg">
      <span className="text-amber-400 mt-0.5">⚠</span>
      <div>
        <span className="text-xs font-semibold text-amber-300">Fragile ruling</span>
        {flip && (
          <p className="text-xs text-amber-200 mt-0.5">
            {flip.field}: <span className="font-mono">{flip.original_value ?? 'current'}</span>
            {' → '}
            <span className="font-mono">{flip.new_value}</span>
            {' flips to '}
            <span className="font-mono">{flip.new_decision}</span>
          </p>
        )}
      </div>
    </div>
  )
}
