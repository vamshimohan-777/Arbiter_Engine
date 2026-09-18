import type { IdentityContext, Ruling } from '@/lib/types'

export default function WhyThisApplies({ identity, ruling }: { identity: IdentityContext; ruling: Ruling }) {
  const controlling = ruling.blocking_clause ?? ruling.citations[0]
  return (
    <details className="rounded-xl border border-neutral-800 bg-neutral-900 px-4 py-3">
      <summary className="cursor-pointer text-xs font-semibold text-neutral-300">Why this applies to you</summary>
      <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-neutral-400">
        <span>✓ Vendor: {identity.vendor}</span><span>✓ Region: {identity.region}</span>
        <span>✓ Department: {identity.department}</span><span>✓ Role: {identity.role}</span>
      </div>
      {controlling && <p className="mt-3 text-xs text-neutral-500">Controlling policy: <span className="font-mono text-neutral-300">{controlling.policy_id}{controlling.section_id ? ` §${controlling.section_id}` : ''}</span></p>}
    </details>
  )
}
