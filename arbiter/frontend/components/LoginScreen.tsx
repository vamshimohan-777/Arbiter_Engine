'use client'

import { FormEvent, useState } from 'react'
import type { IdentityContext } from '@/lib/types'

const ACCOUNTS = [
  { vendor: 'Vendor A', username: 'vendor-a-analyst', label: 'Vendor A · India · Analytics' },
  { vendor: 'Vendor X', username: 'vendor-x-analyst', label: 'Vendor X · India · Analytics' },
  { vendor: 'Vendor X', username: 'vendor-x-security', label: 'Vendor X · India · Security' },
  { vendor: 'Vendor Y', username: 'vendor-y-analyst', label: 'Vendor Y · US · Analytics' },
  { vendor: 'Vendor Y', username: 'vendor-y-finance-eu', label: 'Vendor Y · EU · Finance' },
  { vendor: 'Internal Operations', username: 'eu-support-analyst', label: 'Internal Operations · EU · Support' },
]

export default function LoginScreen({
  onLogin,
}: {
  onLogin: (username: string, password: string, vendor: string) => Promise<IdentityContext>
}) {
  const [selected, setSelected] = useState(ACCOUNTS[0])
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setLoading(true)
    setError(null)
    try {
      await onLogin(selected.username, password, selected.vendor)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not sign in.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="grid min-h-screen place-items-center p-5">
      <form onSubmit={submit} className="glass-panel w-full max-w-md rounded-[30px] p-8">
        <div className="grid h-12 w-12 place-items-center rounded-2xl bg-gradient-to-br from-blue-600 to-teal-400 text-xl font-black text-white shadow-lg shadow-blue-200">A</div>
        <h1 className="mt-5 text-xl font-bold text-slate-900">Arbiter</h1>
        <p className="mt-1 text-sm text-slate-500">Sign in to establish your trusted policy context.</p>

        <label className="mb-1.5 mt-7 block text-xs font-semibold text-slate-600">Demo account</label>
        <select
          value={selected.username}
          onChange={(event) => setSelected(ACCOUNTS.find((a) => a.username === event.target.value) ?? ACCOUNTS[0])}
          className="w-full rounded-xl border border-slate-200 bg-white p-3 text-sm text-slate-700 outline-none focus:border-blue-400"
        >
          {ACCOUNTS.map((account) => <option key={account.username} value={account.username}>{account.label}</option>)}
        </select>

        <label className="mb-1.5 mt-4 block text-xs font-semibold text-slate-600">Username</label>
        <input value={selected.username} readOnly className="w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-500" />
        <label className="mb-1.5 mt-4 block text-xs font-semibold text-slate-600">Password</label>
        <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} required placeholder="Enter account password" className="w-full rounded-xl border border-slate-200 bg-white p-3 text-sm text-slate-700 outline-none focus:border-blue-400" />
        {error && <p className="mt-3 text-xs text-rose-600">{error}</p>}
        <button disabled={loading} className="mt-6 w-full rounded-xl bg-gradient-to-r from-blue-600 to-teal-500 p-3 text-sm font-semibold text-white shadow-md shadow-blue-200 disabled:opacity-50">
          {loading ? 'Signing in…' : 'Sign in'}
        </button>
        <p className="mt-4 text-xs text-slate-500">Credentials are validated against the server-side account store.</p>
      </form>
    </main>
  )
}
