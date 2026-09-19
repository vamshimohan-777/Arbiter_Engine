import type { IdentityContext, Ruling } from '@/lib/types'

export default function WhyThisApplies({ identity, ruling }: { identity: IdentityContext; ruling: Ruling }) {
  const controlling = ruling.blocking_clause ?? ruling.citations[0]
  return (
    <details className="rounded-2xl border border-slate-200 bg-white/65 px-4 py-3">
      <summary className="cursor-pointer text-xs font-semibold text-slate-700">Why this applies to you</summary>
      <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-600">
        <span>✓ Vendor: {identity.vendor}</span><span>✓ Region: {identity.region}</span>
        <span>✓ Department: {identity.department}</span><span>✓ Role: {identity.role}</span>
      </div>
      {controlling && <p className="mt-3 text-xs text-slate-500">Controlling policy: <span className="font-mono text-slate-700">{controlling.policy_id}{controlling.section_id ? ` §${controlling.section_id}` : ''}</span></p>}
    </details>
  )
}
