import type { IdentityContext } from '@/lib/types'

export default function IdentityContextCard({ identity, onSignOut }: { identity: IdentityContext; onSignOut: () => void }) {
  return (
    <div className="p-3 border-b border-neutral-800">
      <p className="text-[10px] text-neutral-500 font-semibold tracking-wider">YOUR POLICY CONTEXT</p>
      <p className="text-xs text-neutral-200 font-medium mt-2">{identity.display_name}</p>
      <p className="text-xs text-neutral-400 mt-1 leading-relaxed">{identity.vendor}<br />{identity.region} · {identity.department}<br />{identity.role}</p>
      <button onClick={onSignOut} className="mt-3 text-xs text-neutral-500 hover:text-neutral-200">Sign out / change account</button>
    </div>
  )
}
