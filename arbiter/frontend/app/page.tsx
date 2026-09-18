'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import type {
  ChatMessage,
  FinalResponse,
  IdentityContext,
  PolicyContext,
  SimulationChange,
  SimulationResult,
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
import IdentityContextCard from '@/components/IdentityContextCard'
import WhyThisApplies from '@/components/WhyThisApplies'

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
  const [simulationChange, setSimulationChange] =
    useState<SimulationChange | null>(null)
  // sessionId must be generated client-side only to avoid SSR hydration mismatch
  const [sessionId, setSessionId] = useState('loading')
  const [initStatus, setInitStatus] = useState<string | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setSessionId(Math.random().toString(36).substring(2, 10))
  }, [])

  useEffect(() => {
    currentIdentity().then(setIdentity).catch(() => setIdentity(null)).finally(() => setAuthLoading(false))
  }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const addMessage = (msg: ChatMessage) =>
    setMessages((prev) => [...prev, msg])

  const replaceLastMessage = (msg: ChatMessage) =>
    setMessages((prev) => [...prev.slice(0, -1), msg])

  // Called when user clicks a suggestion button in the clarification panel
  const handleClarificationSelect = useCallback(
    (field: string, value: string) => {
      if (['vendor', 'region', 'department', 'user_role'].includes(field)) return
      setContext((prev) => ({ ...prev, [field]: value }))
      setShowContextPanel(true)
    },
    []
  )

  const sendAsk = useCallback(async () => {
    if (!input.trim() || isLoading) return
    const question = input.trim()
    setInput('')
    setIsLoading(true)

    addMessage({
      id: crypto.randomUUID(),
      role: 'user',
      content: question,
      timestamp: new Date(),
    })
    addMessage({
      id: crypto.randomUUID(),
      role: 'assistant',
      content: 'Analyzing policies…',
      timestamp: new Date(),
      isLoading: true,
    })

    try {
      const response = await askQuestion({
        question,
        context,
        as_of_date: asOfDate || undefined,
        session_id: sessionId,
      })
      replaceLastMessage({
        id: crypto.randomUUID(),
        role: 'assistant',
        content: response.ruling.explanation,
        response,
        timestamp: new Date(),
      })
    } catch (err) {
      replaceLastMessage({
        id: crypto.randomUUID(),
        role: 'assistant',
        content: `Error: ${err instanceof Error ? err.message : 'Unknown error'}`,
        timestamp: new Date(),
      })
    } finally {
      setIsLoading(false)
    }
  }, [input, isLoading, context, asOfDate, sessionId])

  const sendSimulate = useCallback(
    async (change: SimulationChange, testQuestions?: string[]) => {
      setIsLoading(true)
      addMessage({
        id: crypto.randomUUID(),
        role: 'assistant',
        content: 'Running simulation…',
        timestamp: new Date(),
        isLoading: true,
      })
      try {
        const result = await runSimulation(change, testQuestions)
        replaceLastMessage({
          id: crypto.randomUUID(),
          role: 'assistant',
          content: result.impact_summary,
          simulationResult: result,
          timestamp: new Date(),
        })
      } catch (err) {
        const msg =
          err instanceof Error
            ? err.message
            : typeof err === 'string'
            ? err
            : 'Simulation failed — check server logs'
        replaceLastMessage({
          id: crypto.randomUUID(),
          role: 'assistant',
          content: `Simulation error: ${msg}`,
          timestamp: new Date(),
        })
      } finally {
        setIsLoading(false)
      }
    },
    []
  )

  const switchToSimulate = useCallback((hypotheticalChange: string) => {
    setMode('SIMULATE')
    setSimulationChange({
      change_type: 'REMOVE_EXCEPTION',
      description: hypotheticalChange,
    })
  }, [])

  const handleInit = async () => {
    setInitStatus('Initializing…')
    try {
      const result = await initData()
      setInitStatus(
        `✓ ${result.policies_loaded} policies, ${result.precedents_loaded} precedents loaded`
      )
    } catch (err) {
      setInitStatus(`✗ Init failed: ${err instanceof Error ? err.message : 'unknown'}`)
    }
    setTimeout(() => setInitStatus(null), 5000)
  }

  const userMessages = messages.filter((m) => m.role === 'user')

  const handleLogin = async (username: string, password: string, vendor: string) => {
    const authenticated = await login(username, password, vendor)
    setIdentity(authenticated)
    setContext({})
    setMessages([])
    return authenticated
  }

  const handleSignOut = async () => {
    await logout()
    setIdentity(null)
    setContext({})
    setMessages([])
    setMode('ASK')
  }

  if (authLoading) {
    return <main className="min-h-screen grid place-items-center bg-neutral-950 text-sm text-neutral-500">Loading Arbiter…</main>
  }

  if (!identity) return <LoginScreen onLogin={handleLogin} />

  return (
    <div className="flex h-screen bg-neutral-950 text-neutral-100 overflow-hidden">
      {/* ─── Sidebar ──────────────────────────────────────────── */}
      <aside className="w-60 flex-shrink-0 bg-neutral-900 border-r border-neutral-800 flex flex-col">
        {/* Logo */}
        <div className="p-4 border-b border-neutral-800">
          <h1 className="text-lg font-bold text-neutral-100">⚖ Arbiter</h1>
          <p className="text-xs text-neutral-500 mt-0.5">Policy Reasoning</p>
        </div>

        <IdentityContextCard identity={identity} onSignOut={handleSignOut} />

        {/* Mode toggle */}
        <div className="p-3 border-b border-neutral-800">
          <div className="flex rounded-lg bg-neutral-800 p-0.5">
            {(['ASK', 'SIMULATE'] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`flex-1 py-1.5 text-xs rounded-md font-semibold transition-colors ${
                  mode === m
                    ? m === 'SIMULATE'
                      ? 'bg-blue-700 text-white'
                      : 'bg-neutral-600 text-white'
                    : 'text-neutral-500 hover:text-neutral-300'
                }`}
              >
                {m}
              </button>
            ))}
          </div>
        </div>

        {/* Context panel */}
        <div className="p-3 border-b border-neutral-800">
          <button
            onClick={() => setShowContextPanel((v) => !v)}
            className="text-xs text-neutral-500 hover:text-neutral-300 flex items-center gap-1 w-full"
          >
            <span className="font-semibold">Context</span>
            <span className="ml-auto">{showContextPanel ? '▴' : '▾'}</span>
          </button>
          {showContextPanel && (
            <div className="mt-2 space-y-2">
              {(['dataset'] as const).map(
                (field) => (
                  <div key={field}>
                    <label className="text-xs text-neutral-600 capitalize">
                      {field}
                    </label>
                    <input
                      type="text"
                      value={(context as Record<string, string>)[field] ?? ''}
                      onChange={(e) =>
                        setContext((prev) => ({
                          ...prev,
                          [field]: e.target.value || undefined,
                        }))
                      }
                      placeholder="e.g. Dataset Y"
                      className="w-full mt-0.5 px-2 py-1 bg-neutral-800 border border-neutral-700 rounded text-xs text-neutral-200 placeholder-neutral-700 focus:outline-none focus:border-neutral-500"
                    />
                  </div>
                )
              )}
              <div>
                <label className="text-xs text-neutral-600">As-of date</label>
                <input
                  type="date"
                  value={asOfDate}
                  onChange={(e) => setAsOfDate(e.target.value)}
                  className="w-full mt-0.5 px-2 py-1 bg-neutral-800 border border-neutral-700 rounded text-xs text-neutral-200 focus:outline-none focus:border-neutral-500"
                />
              </div>
            </div>
          )}
        </div>

        {/* History */}
        <div className="flex-1 overflow-y-auto p-3">
          <p className="text-xs text-neutral-700 uppercase tracking-wider mb-2">
            History
          </p>
          {userMessages.length === 0 && (
            <p className="text-xs text-neutral-700">No queries yet.</p>
          )}
          {userMessages.map((m) => (
            <div
              key={m.id}
              className="text-xs text-neutral-500 hover:text-neutral-300 py-1.5 truncate cursor-pointer"
            >
              {m.content.slice(0, 48)}
              {m.content.length > 48 ? '…' : ''}
            </div>
          ))}
        </div>

        {/* Init button */}
        <div className="p-3 border-t border-neutral-800">
          <button
            onClick={handleInit}
            className="w-full py-2 bg-neutral-800 hover:bg-neutral-700 rounded-lg text-xs text-neutral-400 transition-colors"
          >
            ⟳ Initialize / Reload Data
          </button>
          {initStatus && (
            <p className="text-xs text-neutral-500 mt-1 text-center leading-tight">
              {initStatus}
            </p>
          )}
        </div>
      </aside>

      {/* ─── Main Area ────────────────────────────────────────── */}
      <main className="flex-1 flex flex-col min-w-0">
        {/* Header bar */}
        <div className="h-11 border-b border-neutral-800 flex items-center px-5">
          <span className="text-sm text-neutral-500">
            {mode === 'ASK' ? 'Policy Query' : 'What-If Simulation'}
          </span>
          <span className="ml-auto text-xs text-neutral-700">
            Session: {sessionId}
          </span>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-5 py-5 space-y-6">
          {/* Empty states */}
          {messages.length === 0 && mode === 'ASK' && (
            <div className="text-center mt-24 text-neutral-700 select-none">
              <p className="text-4xl mb-4">⚖</p>
              <p className="text-sm font-medium">Ask a policy question</p>
              <p className="text-xs mt-2 max-w-sm mx-auto text-neutral-700">
                e.g. &ldquo;Can Analytics share Dataset Y with Vendor X in India
                today?&rdquo;
              </p>
            </div>
          )}

          {messages.length === 0 && mode === 'SIMULATE' && (
            <SimulatePanel
              initialChange={simulationChange}
              onSimulate={sendSimulate}
              isLoading={isLoading}
            />
          )}

          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex ${
                msg.role === 'user' ? 'justify-end' : 'justify-start'
              }`}
            >
              {msg.role === 'user' ? (
                <div className="max-w-lg bg-neutral-800 rounded-2xl rounded-tr-sm px-4 py-3 text-sm text-neutral-100">
                  {msg.content}
                </div>
              ) : (
                <div className="max-w-3xl w-full space-y-3">
                  {msg.isLoading ? (
                    <div className="flex items-center gap-2 text-neutral-500 text-sm">
                      <span className="flex gap-1">
                        {[0, 150, 300].map((d) => (
                          <span
                            key={d}
                            className="w-1.5 h-1.5 bg-neutral-500 rounded-full dot-bounce"
                            style={{ animationDelay: `${d}ms` }}
                          />
                        ))}
                      </span>
                      <span>{msg.content}</span>
                    </div>
                  ) : msg.simulationResult ? (
                    <SimulationReport result={msg.simulationResult} />
                  ) : msg.response ? (
                    <ArbiterResponse
                      response={msg.response}
                      onSwitchToSimulate={switchToSimulate}
                      onSelectOption={handleClarificationSelect}
                      identity={identity}
                    />
                  ) : (
                    <p className="text-sm text-neutral-300">{msg.content}</p>
                  )}
                </div>
              )}
            </div>
          ))}
          {/* Inline SimulatePanel — shown after at least one message in SIMULATE mode */}
          {mode === 'SIMULATE' && messages.length > 0 && (
            <div className="max-w-3xl w-full mx-auto">
              <SimulatePanel
                initialChange={simulationChange}
                onSimulate={sendSimulate}
                isLoading={isLoading}
              />
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input bar */}
        {mode === 'ASK' && (
          <div className="border-t border-neutral-800 p-4">
            <div className="flex gap-2 max-w-3xl mx-auto">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) =>
                  e.key === 'Enter' && !e.shiftKey && sendAsk()
                }
                placeholder={`Ask as ${identity.vendor}, ${identity.region}, ${identity.department}…`}
                disabled={isLoading}
                className="flex-1 px-4 py-3 bg-neutral-800 border border-neutral-700 rounded-xl text-sm text-neutral-100 placeholder-neutral-600 focus:outline-none focus:border-neutral-500 disabled:opacity-40"
              />
              <button
                onClick={sendAsk}
                disabled={isLoading || !input.trim()}
                className="px-4 py-3 bg-neutral-700 hover:bg-neutral-600 disabled:opacity-40 rounded-xl text-sm transition-colors"
              >
                ➤
              </button>
            </div>
            {messages.length > 0 && (
              <div className="flex justify-center mt-2">
                <button
                  onClick={() => setMode('SIMULATE')}
                  className="text-xs text-neutral-600 hover:text-blue-400 transition-colors"
                >
                  ⚡ Switch to Simulation mode
                </button>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// ArbiterResponse — renders a single assistant response card
// ─────────────────────────────────────────────────────────────
function ArbiterResponse({
  response,
  onSwitchToSimulate,
  onSelectOption,
  identity,
}: {
  response: FinalResponse
  onSwitchToSimulate: (change: string) => void
  onSelectOption: (field: string, value: string) => void
  identity: IdentityContext
}) {
  const [showGraph, setShowGraph] = useState(false)

  const processingS = (response.processing_time_ms / 1000).toFixed(1)

  return (
    <div className="space-y-3">
      {/* Clarification */}
      {response.clarification && (
        <ClarificationPrompt
          clarification={response.clarification}
          onSelectOption={onSelectOption}
        />
      )}

      {/* Verdict */}
      {!response.clarification && <VerdictCard ruling={response.ruling} />}

      {!response.clarification && (
        <WhyThisApplies identity={identity} ruling={response.ruling} />
      )}

      {/* Checker flag */}
      {response.checker_result?.status === 'CHECK_UNAVAILABLE' && (
        <div className="bg-amber-950 border border-amber-800 rounded-xl p-4">
          <p className="text-xs font-semibold text-amber-400">
            ⚠ Adversarial verification unavailable
          </p>
          <p className="text-xs text-amber-200 mt-1">
            The ruling is shown, but it could not be independently checked.
          </p>
        </div>
      )}
      {response.checker_result &&
        response.checker_result.status !== 'CHECK_UNAVAILABLE' &&
        !response.checker_result.approved && (
          <div className="bg-amber-950 border border-amber-800 rounded-xl p-4">
            <p className="text-xs font-semibold text-amber-400 mb-2">
              ⚠ Checker flagged issues — ruling was revised
            </p>
            {response.checker_result.false_premise_flags.length > 0 && (
              <div className="mb-2">
                <p className="text-xs text-amber-300 mb-1">
                  False premises rejected:
                </p>
                <ul className="text-xs text-amber-200 space-y-0.5 list-disc list-inside">
                  {response.checker_result.false_premise_flags.map(
                    (f, i) => (
                      <li key={i}>{f}</li>
                    )
                  )}
                </ul>
              </div>
            )}
            {response.checker_result.objections.length > 0 && (
              <div>
                <p className="text-xs text-amber-300 mb-1">Objections:</p>
                <ul className="text-xs text-amber-200 space-y-0.5 list-disc list-inside">
                  {response.checker_result.objections.map((o, i) => (
                    <li key={i}>{o}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

      {/* Sensitivity + Precedent badges */}
      {(response.sensitivity || response.precedent) && (
        <div className="flex flex-wrap gap-2">
          {response.sensitivity && (
            <SensitivityBadge sensitivity={response.sensitivity} />
          )}
          {response.precedent && (
            <PrecedentBadge precedent={response.precedent} />
          )}
        </div>
      )}

      {/* Citations are primary policy evidence and remain visible. */}
      {response.ruling.citations.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-neutral-400">
            Citations ({response.ruling.citations.length})
          </p>
          <CitationList citations={response.ruling.citations} />
        </div>
      )}

      {/* Remediation */}
      {response.remediation && (
        <RemediationPanel
          remediation={response.remediation}
          onSwitchToSimulate={onSwitchToSimulate}
        />
      )}

      {/* Graph collapsible */}
      {response.graph_nodes.length > 0 && (
        <div>
          <button
            onClick={() => setShowGraph((v) => !v)}
            className="text-xs text-neutral-500 hover:text-neutral-300"
          >
            {showGraph ? '▾' : '▸'} Reasoning graph (
            {response.graph_nodes.length} nodes,{' '}
            {response.graph_edges.length} edges)
          </button>
          {showGraph && (
            <div className="mt-2 h-72 rounded-xl overflow-hidden border border-neutral-800">
              <ReasoningGraph
                nodes={response.graph_nodes}
                edges={response.graph_edges}
              />
            </div>
          )}
        </div>
      )}

      {/* Footer */}
      <p className="text-xs text-neutral-700">
        Processed in {processingS}s · Session {response.session_id}
      </p>
    </div>
  )
}
