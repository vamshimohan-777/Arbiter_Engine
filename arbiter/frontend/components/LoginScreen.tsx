'use client'

import { FormEvent, useState } from 'react'
import type { IdentityContext } from '@/lib/types'

const ACCOUNTS = [
  { vendor: 'Vendor A', username: 'vendor-a-analyst', label: 'Vendor A · India · Analytics' },
  { vendor: 'Vendor X', username: 'vendor-x-analyst', label: 'Vendor X · India · Analytics' },
  { vendor: 'Vendor X', username: 'vendor-x-security', label: 'Vendor X · India · Security' },
  { vendor: 'Vendor Y', username: 'vendor-y-analyst', label: 'Vendor Y · US · Analytics' },
  { vendor: 'Vendor Y', username: 'vendor-y-finance-eu', label: 'Vendor Y · EU · Finance' },
]

export default function LoginScreen({
  onLogin,
}: {
  onLogin: (username: string, password: string, vendor: string) => Promise<IdentityContext>
}) {
  const [selected, setSelected] = useState(ACCOUNTS[0])
  const [password, setPassword] = useState('arbiter-demo')
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
    <main className="min-h-screen bg-neutral-950 text-neutral-100 grid place-items-center p-5">
      <form onSubmit={submit} className="w-full max-w-md rounded-2xl border border-neutral-800 bg-neutral-900 p-7 shadow-2xl">
        <p className="text-3xl mb-2">⚖</p>
        <h1 className="text-xl font-bold">Arbiter</h1>
        <p className="text-sm text-neutral-500 mt-1">Sign in to establish your trusted policy context.</p>

        <label className="block text-xs font-semibold text-neutral-400 mt-7 mb-1.5">Demo account</label>
        <select
          value={selected.username}
          onChange={(event) => setSelected(ACCOUNTS.find((a) => a.username === event.target.value) ?? ACCOUNTS[0])}
          className="w-full rounded-lg bg-neutral-800 border border-neutral-700 p-3 text-sm"
        >
          {ACCOUNTS.map((account) => <option key={account.username} value={account.username}>{account.label}</option>)}
        </select>

        <label className="block text-xs font-semibold text-neutral-400 mt-4 mb-1.5">Username</label>
        <input value={selected.username} readOnly className="w-full rounded-lg bg-neutral-800 border border-neutral-700 p-3 text-sm text-neutral-400" />
        <label className="block text-xs font-semibold text-neutral-400 mt-4 mb-1.5">Password</label>
        <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} className="w-full rounded-lg bg-neutral-800 border border-neutral-700 p-3 text-sm" />
        {error && <p className="mt-3 text-xs text-red-300">{error}</p>}
        <button disabled={loading} className="w-full mt-6 rounded-lg bg-blue-700 hover:bg-blue-600 disabled:opacity-50 p-3 text-sm font-semibold">
          {loading ? 'Signing in…' : 'Sign in'}
        </button>
        <p className="mt-4 text-xs text-neutral-600">Demo password for all accounts: <span className="font-mono">arbiter-demo</span></p>
      </form>
    </main>
  )
}
