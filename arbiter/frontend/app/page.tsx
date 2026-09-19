'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import type {
  ChatMessage,
  FinalResponse,
  IdentityContext,
  PolicyContext,
  SensitivityResult,
  SimulationChange,
} from '@/lib/types'
import { askQuestion, runSimulation, initData, currentIdentity, login, logout } from '@/lib/api'
import VerdictCard from '@/components/VerdictCard'
import RemediationPanel from '@/components/RemediationPanel'
import ReasoningGraph from '@/components/ReasoningGraph'
import SensitivityBadge from '@/components/SensitivityBadge'
import PrecedentBadge from '@/components/PrecedentBadge'
import CitationList from '@/components/CitationList'
import ClarificationPrompt from '@/components/ClarificationPrompt'
import SimulationReport from '@/components/SimulationReport'
import SimulatePanel from '@/components/SimulatePanel'
import LoginScreen from '@/components/LoginScreen'
import WhyThisApplies from '@/components/WhyThisApplies'
import AgentExecutionBox from '@/components/AgentExecutionBox'

const PIPELINE = [
  ['1', 'Retrieval', 'scope policy evidence'],
  ['2', 'Resolution', 'apply versions and scope'],
  ['3', 'Adversarial check', 'verify the draft'],
  ['4', 'Precedent', 'compare history'],
  ['5', 'Sensitivity', 'test nearby changes'],
]

export default function Home() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [mode, setMode] = useState<'ASK' | 'SIMULATE'>('ASK')
  const [isLoading, setIsLoading] = useState(false)
  const [context, setContext] = useState<PolicyContext>({})
  const [identity, setIdentity] = useState<IdentityContext | null>(null)
  const [authLoading, setAuthLoading] = useState(true)
  const [asOfDate, setAsOfDate] = useState('')
  const [showContextPanel, setShowContextPanel] = useState(false)
  const [simulationChange, setSimulationChange] = useState<SimulationChange | null>(null)
  const [sessionId, setSessionId] = useState('loading')
  const [initStatus, setInitStatus] = useState<string | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => { setSessionId(Math.random().toString(36).substring(2, 10)) }, [])
  useEffect(() => {
    currentIdentity().then(setIdentity).catch(() => setIdentity(null)).finally(() => setAuthLoading(false))
  }, [])
  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  const addMessage = (msg: ChatMessage) => setMessages((prev) => [...prev, msg])
  const replaceLastMessage = (msg: ChatMessage) => setMessages((prev) => [...prev.slice(0, -1), msg])

  const handleClarificationSelect = useCallback((field: string, value: string) => {
    if (['vendor', 'region', 'department', 'user_role'].includes(field)) return
    setContext((prev) => ({ ...prev, [field]: value }))
    setShowContextPanel(true)
  }, [])

  const sendAsk = useCallback(async () => {
    if (!input.trim() || isLoading) return
    const question = input.trim()
    setInput('')
    setIsLoading(true)
    addMessage({ id: crypto.randomUUID(), role: 'user', content: question, timestamp: new Date() })
    addMessage({ id: crypto.randomUUID(), role: 'assistant', content: 'Tracing applicable policy evidence…', timestamp: new Date(), isLoading: true })
    try {
      const response = await askQuestion({ question, context, as_of_date: asOfDate || undefined, session_id: sessionId })
      replaceLastMessage({ id: crypto.randomUUID(), role: 'assistant', content: response.ruling.explanation, response, timestamp: new Date() })
    } catch (err) {
      replaceLastMessage({ id: crypto.randomUUID(), role: 'assistant', content: `Error: ${err instanceof Error ? err.message : 'Unknown error'}`, timestamp: new Date() })
    } finally { setIsLoading(false) }
  }, [input, isLoading, context, asOfDate, sessionId])

  const sendSimulate = useCallback(async (change: SimulationChange, testQuestions?: string[]) => {
    setIsLoading(true)
    addMessage({ id: crypto.randomUUID(), role: 'assistant', content: 'Evaluating the hypothetical policy change…', timestamp: new Date(), isLoading: true })
    try {
      const result = await runSimulation(change, testQuestions)
      replaceLastMessage({ id: crypto.randomUUID(), role: 'assistant', content: result.impact_summary, simulationResult: result, timestamp: new Date() })
    } catch (err) {
      const message = err instanceof Error ? err.message : typeof err === 'string' ? err : 'Simulation failed — check server logs'
      replaceLastMessage({ id: crypto.randomUUID(), role: 'assistant', content: `Simulation error: ${message}`, timestamp: new Date() })
    } finally { setIsLoading(false) }
  }, [])

  const switchToSimulate = useCallback((description: string) => {
    setMode('SIMULATE')
    setSimulationChange({ change_type: 'REMOVE_EXCEPTION', description })
  }, [])

  const handleInit = async () => {
    setInitStatus('Synchronizing corpus…')
    try {
      const result = await initData()
      setInitStatus(`${result.policies_loaded} policies · ${result.precedents_loaded} precedents loaded`)
    } catch (err) { setInitStatus(`Sync failed: ${err instanceof Error ? err.message : 'unknown'}`) }
    setTimeout(() => setInitStatus(null), 5000)
  }

  const handleLogin = async (username: string, password: string, vendor: string) => {
    const authenticated = await login(username, password, vendor)
    setIdentity(authenticated); setContext({}); setMessages([])
    return authenticated
  }
  const handleSignOut = async () => { await logout(); setIdentity(null); setContext({}); setMessages([]); setMode('ASK') }

  if (authLoading) return <main className="grid min-h-screen place-items-center text-sm text-slate-500">Loading Arbiter…</main>
  if (!identity) return <LoginScreen onLogin={handleLogin} />

  const userMessages = messages.filter((message) => message.role === 'user')
  const contextRows = [
    ['Region', identity.region], ['Department', identity.department], ['Vendor', identity.vendor],
    ['Dataset', context.dataset || 'Not specified'], ['As-of', asOfDate || 'Current date'],
  ]

  return (
    <main className="min-h-screen px-3 py-3 sm:px-5 lg:h-[100dvh] lg:overflow-hidden lg:px-7">
      <div className="mx-auto max-w-[1600px] lg:flex lg:h-full lg:flex-col">
        <header className="glass-panel flex min-h-[82px] shrink-0 flex-wrap items-center gap-4 rounded-[28px] px-5 py-3 sm:px-6">
          <div className="flex items-center gap-3 pr-4 sm:border-r sm:border-slate-200/80">
            <div className="grid h-11 w-11 place-items-center rounded-2xl bg-gradient-to-br from-blue-600 to-teal-400 text-lg font-black text-white shadow-lg shadow-blue-200">A</div>
            <div><h1 className="font-bold tracking-tight text-slate-900">Arbiter</h1><p className="text-xs text-slate-500">Policy reasoning workspace</p></div>
          </div>
          <nav className="flex rounded-xl bg-slate-100/80 p-1 text-sm font-medium text-slate-500">
            {(['ASK', 'SIMULATE'] as const).map((item) => <button key={item} onClick={() => setMode(item)} className={`rounded-lg px-4 py-2 transition ${mode === item ? 'bg-white text-slate-900 shadow-sm' : 'hover:text-slate-800'}`}>{item === 'ASK' ? 'Ask' : 'Simulate'}</button>)}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-xs">
            <span className="hidden rounded-full bg-emerald-50 px-3 py-2 font-mono text-emerald-700 sm:inline-flex"><span className="mr-2 h-2 w-2 rounded-full bg-teal-400" />Authenticated context</span>
            <button onClick={handleSignOut} className="rounded-xl border border-slate-200 bg-white px-3 py-2 font-medium text-slate-600 hover:border-slate-300">Sign out</button>
          </div>
        </header>

        <div className="mt-5 grid gap-5 lg:min-h-0 lg:flex-1 lg:overflow-hidden lg:grid-cols-[280px_minmax(0,1fr)]">
          <aside className="space-y-4 lg:h-full lg:min-h-0 lg:overflow-y-scroll lg:overscroll-contain lg:pr-2">
            <section className="glass-panel rounded-3xl p-5 lg:sticky lg:top-0 lg:z-20 lg:shadow-[0_18px_45px_rgba(50,74,115,0.14)]">
              <p className="eyebrow">Case context</p>
              <p className="mt-3 text-sm font-semibold text-slate-800">{identity.display_name}</p>
              <dl className="mt-4 space-y-2.5 text-sm">
                {contextRows.map(([label, value]) => <div className="flex items-center justify-between gap-3" key={label}><dt className="text-slate-500">{label}</dt><dd className="rounded-full bg-slate-100 px-2.5 py-1 font-mono text-xs text-slate-700">{value}</dd></div>)}
              </dl>
              <button onClick={() => setShowContextPanel((value) => !value)} className="mt-5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-600 hover:border-blue-200 hover:text-blue-700">{showContextPanel ? 'Hide request context' : 'Refine request context'}</button>
              {showContextPanel && <div className="mt-3 space-y-3 border-t border-slate-200 pt-3"><label className="block text-xs font-medium text-slate-600">Dataset<input value={context.dataset ?? ''} onChange={(event) => setContext((previous) => ({ ...previous, dataset: event.target.value || undefined }))} placeholder="Dataset name" className="mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-blue-400" /></label><label className="block text-xs font-medium text-slate-600">As-of date<input type="date" value={asOfDate} onChange={(event) => setAsOfDate(event.target.value)} className="mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-blue-400" /></label></div>}
            </section>

            <section className="glass-panel rounded-3xl p-5">
              <p className="eyebrow">Reasoning pipeline</p>
              <div className="mt-4 space-y-2">
                {PIPELINE.map(([number, name, detail]) => <div key={number} className="flex items-center gap-3 rounded-2xl bg-white/65 px-3 py-2.5"><span className="grid h-6 w-6 place-items-center rounded-full bg-emerald-100 text-xs font-bold text-emerald-700">{number}</span><span><span className="block text-xs font-semibold text-slate-700">{name}</span><span className="block text-[11px] text-slate-500">{detail}</span></span><span className="ml-auto h-2 w-2 rounded-full bg-emerald-400" /></div>)}
              </div>
            </section>

            <section className="glass-panel rounded-3xl p-5">
              <div className="flex items-center justify-between"><p className="eyebrow">Query history</p><span className="text-xs text-slate-400">{userMessages.length}</span></div>
              <div className="mt-3 max-h-36 space-y-1 overflow-y-auto">{userMessages.length === 0 ? <p className="text-xs text-slate-500">Your submitted queries will appear here.</p> : userMessages.map((message) => <p key={message.id} className="truncate rounded-lg px-2 py-1.5 text-xs text-slate-600 hover:bg-white">{message.content}</p>)}</div>
              <button onClick={handleInit} className="mt-4 w-full rounded-xl bg-slate-900 px-3 py-2 text-xs font-semibold text-white transition hover:bg-slate-700">Sync policy corpus</button>
              {initStatus && <p className="mt-2 text-center text-xs text-slate-500">{initStatus}</p>}
            </section>
          </aside>

          <section className="relative flex min-h-[calc(100vh-125px)] min-w-0 flex-col overflow-hidden rounded-[30px] border border-white/80 bg-white/38 shadow-[0_18px_45px_rgba(50,74,115,0.08)] lg:h-full lg:min-h-0">
            <div className="flex items-center gap-3 border-b border-slate-200/70 px-6 py-4"><div><p className="eyebrow">{mode === 'ASK' ? 'Policy query' : 'What-if simulation'}</p><p className="mt-1 text-sm text-slate-600">{mode === 'ASK' ? 'Grounded decisions with transparent agent provenance.' : 'Test a hypothetical change without modifying the policy corpus.'}</p></div><div className="ml-auto flex items-center gap-2"><>{asOfDate && <button onClick={() => setAsOfDate('')} title="Clear historical date and use today's policy state" className="rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 font-mono text-[11px] text-amber-800 hover:bg-amber-100">Historical: {asOfDate} ×</button>}</><span className="hidden font-mono text-xs text-slate-400 sm:block">session {sessionId}</span></div></div>

            <div className="min-h-0 flex-1 space-y-6 overflow-y-scroll overscroll-contain px-4 py-6 pb-40 sm:px-7">
              {messages.length === 0 && mode === 'ASK' && <div className="glass-panel mx-auto mt-12 max-w-2xl rounded-[28px] p-8 text-center"><div className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-gradient-to-br from-blue-600 to-teal-400 text-xl text-white">⚖</div><h2 className="mt-4 text-lg font-bold text-slate-800">Ready to reason through policy</h2><p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-slate-500">Your authenticated role determines the trusted vendor, region, and department. Add a policy question below to begin.</p></div>}
              {messages.length === 0 && mode === 'SIMULATE' && <SimulatePanel initialChange={simulationChange} onSimulate={sendSimulate} isLoading={isLoading} />}
              {messages.map((message) => <div key={message.id} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>{message.role === 'user' ? <div className="max-w-xl rounded-3xl rounded-tr-md bg-slate-900 px-5 py-3.5 text-sm leading-relaxed text-white shadow-lg shadow-slate-300/40">{message.content}</div> : <div className="w-full max-w-4xl space-y-3">{message.isLoading ? <div className="glass-panel flex items-center gap-3 rounded-2xl px-4 py-3 text-sm text-slate-600"><span className="flex gap-1">{[0, 150, 300].map((delay) => <span key={delay} className="dot-bounce h-1.5 w-1.5 rounded-full bg-blue-500" style={{ animationDelay: `${delay}ms` }} />)}</span>{message.content}</div> : message.simulationResult ? <SimulationReport result={message.simulationResult} /> : message.response ? <ArbiterResponse response={message.response} onSwitchToSimulate={switchToSimulate} onSelectOption={handleClarificationSelect} identity={identity} /> : <p className="rounded-xl bg-rose-50 p-3 text-sm text-rose-700">{message.content}</p>}</div>}</div>)}
              {mode === 'SIMULATE' && messages.length > 0 && <SimulatePanel initialChange={simulationChange} onSimulate={sendSimulate} isLoading={isLoading} />}
              <div ref={messagesEndRef} />
            </div>

            {mode === 'ASK' && <div className="fixed inset-x-3 bottom-3 z-50 mx-auto w-auto max-w-4xl sm:bottom-5 sm:w-[min(92vw,56rem)] lg:absolute lg:inset-x-5 lg:bottom-5 lg:mx-0 lg:w-auto lg:max-w-none"><div className="rounded-[22px] border border-slate-200/90 bg-white/92 p-2 shadow-[0_18px_45px_rgba(50,74,115,0.2)] backdrop-blur-xl"><textarea value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendAsk() } }} placeholder="Ask a policy question…" disabled={isLoading} rows={2} className="w-full resize-none bg-transparent px-3 py-2 text-sm leading-relaxed text-slate-800 outline-none placeholder:text-slate-400 disabled:opacity-50" /><div className="flex items-center gap-2 border-t border-slate-100 px-2 pt-2"><span className="hidden text-xs text-slate-400 sm:block">Enter to submit · Shift + Enter for a new line</span><button onClick={sendAsk} disabled={isLoading || !input.trim()} className="ml-auto rounded-xl bg-gradient-to-r from-blue-600 to-teal-500 px-4 py-2 text-xs font-bold text-white shadow-md shadow-blue-200 transition hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-40">Ask Arbiter →</button></div></div></div>}
          </section>
        </div>
      </div>
    </main>
  )
}

function ArbiterResponse({ response, onSwitchToSimulate, onSelectOption, identity }: { response: FinalResponse; onSwitchToSimulate: (change: string) => void; onSelectOption: (field: string, value: string) => void; identity: IdentityContext }) {
  const [showGraph, setShowGraph] = useState(false)
  const processingSeconds = (response.processing_time_ms / 1000).toFixed(1)
  // Always reserve a visible decision-boundary result. This prevents an older
  // backend response or a failed optional check from making sensitivity look
  // like it was silently skipped.
  const sensitivity: SensitivityResult = response.sensitivity ?? {
    ruling_id: response.ruling.ruling_id,
    flips: [],
    is_fragile: false,
    summary: response.clarification
      ? 'Sensitivity is not run until the missing policy context is clarified.'
      : 'Sensitivity data was not returned by the active backend. Restart the backend and submit the question again.',
    total_perturbations_tested: 0,
    status: 'CHECK_UNAVAILABLE',
  }
  return <div className="space-y-4">
    {response.clarification && <ClarificationPrompt clarification={response.clarification} onSelectOption={onSelectOption} />}
    {!response.clarification && <VerdictCard ruling={response.ruling} />}
    {!response.clarification && <WhyThisApplies identity={identity} ruling={response.ruling} />}
    <AgentExecutionBox executions={response.agent_executions ?? []} />
    {response.checker_result?.status === 'CHECK_UNAVAILABLE' && <Notice title="Adversarial verification unavailable" detail="The ruling is shown, but it could not be independently checked." />}
    {response.checker_result && response.checker_result.status !== 'CHECK_UNAVAILABLE' && !response.checker_result.approved && <Notice title="Checker flagged issues — ruling was revised" detail={[...response.checker_result.false_premise_flags, ...response.checker_result.objections].join(' · ') || response.checker_result.explanation} />}
    <div className="grid gap-3 md:grid-cols-2"><SensitivityBadge sensitivity={sensitivity} />{response.precedent && <PrecedentBadge precedent={response.precedent} />}</div>
    {response.ruling.citations.length > 0 && <section><p className="eyebrow mb-2">Evidence chain · {response.ruling.citations.length} citations</p><CitationList citations={response.ruling.citations} /></section>}
    {response.remediation && <RemediationPanel remediation={response.remediation} onSwitchToSimulate={onSwitchToSimulate} />}
    {response.graph_nodes.length > 0 && <section className="glass-panel rounded-2xl p-4"><button onClick={() => setShowGraph((value) => !value)} className="text-xs font-semibold text-slate-600 hover:text-blue-700">{showGraph ? '▾ Hide' : '▸ Show'} reasoning graph · {response.graph_nodes.length} nodes · {response.graph_edges.length} edges</button>{showGraph && <div className="mt-3 h-72 overflow-hidden rounded-xl border border-slate-200"><ReasoningGraph nodes={response.graph_nodes} edges={response.graph_edges} /></div>}</section>}
    <p className="px-1 text-xs text-slate-400">Processed in {processingSeconds}s · Session {response.session_id}</p>
  </div>
}

function Notice({ title, detail }: { title: string; detail: string }) {
  return <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3"><p className="text-xs font-semibold text-amber-800">⚠ {title}</p><p className="mt-1 text-xs leading-relaxed text-amber-700">{detail}</p></div>
}
