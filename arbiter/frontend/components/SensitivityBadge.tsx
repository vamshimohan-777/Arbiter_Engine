import type { SensitivityResult } from '@/lib/types'

export default function SensitivityBadge({
  sensitivity,
}: {
  sensitivity: SensitivityResult
}) {
  const heading = <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-slate-500">Decision sensitivity</p>

  if (sensitivity.status === 'CHECK_UNAVAILABLE') {
    return (
      <section className="rounded-2xl border border-amber-200 bg-amber-50/85 px-4 py-3 shadow-sm">
        {heading}
        <div className="mt-2 flex items-start gap-2">
        <span className="text-amber-500">⚠</span>
        <div>
          <span className="text-sm font-semibold text-amber-900">Sensitivity check unavailable</span>
          <p className="mt-0.5 text-xs leading-relaxed text-amber-800">{sensitivity.summary || 'The ruling was not assessed for nearby decision flips.'}</p>
        </div>
        </div>
      </section>
    )
  }

  if (sensitivity.status === 'NO_ELIGIBLE_CASES') {
    return (
      <section className="rounded-2xl border border-slate-200 bg-white/80 px-4 py-3 shadow-sm">
        {heading}
        <div className="mt-2 flex items-start gap-2">
        <span className="text-slate-400">○</span>
        <div>
          <span className="text-sm font-semibold text-slate-800">Sensitivity not applicable</span>
          <p className="mt-0.5 text-xs leading-relaxed text-slate-600">{sensitivity.summary}</p>
        </div>
        </div>
      </section>
    )
  }

  if (!sensitivity.is_fragile) {
    return (
      <section className="rounded-2xl border border-emerald-200 bg-emerald-50/80 px-4 py-3 shadow-sm">
        {heading}
        <div className="mt-2 flex items-center gap-2">
        <span className="text-emerald-600">🛡</span>
        <div>
          <span className="text-sm font-semibold text-emerald-900">Stable ruling</span>
          <p className="mt-0.5 text-xs leading-relaxed text-emerald-800">{sensitivity.summary}</p>
        </div>
        </div>
      </section>
    )
  }

  const flip = sensitivity.nearest_flip
  return (
    <section className="rounded-2xl border border-amber-300 bg-amber-50/90 px-4 py-3 shadow-sm">
      {heading}
      <div className="mt-2 flex items-start gap-2">
      <span className="mt-0.5 text-amber-500">⚠</span>
      <div>
        <span className="text-sm font-semibold text-amber-900">Fragile ruling</span>
        {flip && (
          <p className="mt-0.5 text-xs leading-relaxed text-amber-800">
            {flip.field}: <span className="font-mono">{flip.original_value ?? 'current'}</span>
            {' → '}
            <span className="font-mono">{flip.new_value}</span>
            {' flips to '}
            <span className="font-mono">{flip.new_decision}</span>
          </p>
        )}
      </div>
      </div>
    </section>
  )
}
