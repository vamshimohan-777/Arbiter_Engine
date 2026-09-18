'use client'

import { useState } from 'react'
import type { RemediationResult } from '@/lib/types'

interface Props {
  remediation: RemediationResult
  onSwitchToSimulate: (hypotheticalChange: string) => void
}

export default function RemediationPanel({ remediation, onSwitchToSimulate }: Props) {
  const [expanded, setExpanded] = useState(true)

  // ── WAIVER path ────────────────────────────────────────────────────────────
  if (remediation.remediation_type === 'WAIVER') {
    return (
      <div className="border border-green-800 rounded-xl overflow-hidden">
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full px-4 py-3 bg-green-950 hover:bg-green-900 flex items-center gap-2 text-left transition-colors"
        >
          <span className="text-green-400">{expanded ? '▾' : '▸'}</span>
          <span className="text-sm text-green-300 font-semibold">Path to Permission</span>
          <span className="ml-auto text-xs text-green-600 font-mono">WAIVER AVAILABLE</span>
        </button>

        {expanded && (
          <div className="p-4 bg-neutral-900 border-t border-green-900 space-y-4">
            {/* Groq explanation */}
            <div className="rounded-lg bg-green-950/50 border border-green-900 p-3">
              <p className="text-xs font-semibold text-green-400 uppercase tracking-wider mb-1">
                Analysis
              </p>
              <p className="text-sm text-green-100 leading-relaxed">{remediation.explanation}</p>
            </div>

            {remediation.required_approval && (
              <p className="text-xs text-neutral-300">
                Final approval required:{' '}
                <span className="text-green-400 font-semibold">{remediation.required_approval}</span>
              </p>
            )}

            {remediation.steps.length > 0 && (
              <div className="space-y-3">
                <p className="text-xs font-semibold text-neutral-400 uppercase tracking-wider">
                  Steps to obtain permission
                </p>
                {remediation.steps.map((step) => (
                  <div key={step.step_number} className="flex gap-3">
                    <span className="flex-shrink-0 w-6 h-6 rounded-full bg-green-900 border border-green-700 text-green-300 text-xs flex items-center justify-center font-bold">
                      {step.step_number}
                    </span>
                    <div>
                      <p className="text-xs text-neutral-200 leading-relaxed">{step.description}</p>
                      {step.required_approval && (
                        <p className="text-xs text-neutral-500 mt-0.5">
                          Requires: {step.required_approval}
                        </p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {remediation.supporting_policy_ids && remediation.supporting_policy_ids.length > 0 && (
              <p className="text-xs text-neutral-500">
                Based on: {remediation.supporting_policy_ids.join(', ')}
              </p>
            )}
          </div>
        )}
      </div>
    )
  }

  // ── SIMULATION path — no waiver exists ────────────────────────────────────
  return (
    <div className="border border-blue-800 rounded-xl overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 bg-blue-950 flex items-center gap-2">
        <span className="text-blue-400">⚡</span>
        <span className="text-sm text-blue-300 font-semibold">No Waiver Path Exists</span>
        <span className="ml-auto text-xs text-blue-700 font-mono">SIMULATION ONLY</span>
      </div>

      {/* Groq-generated explanation — shown prominently */}
      <div className="p-4 bg-neutral-900 border-t border-blue-900 space-y-3">
        <div className="rounded-lg bg-blue-950/40 border border-blue-900 p-3">
          <p className="text-xs font-semibold text-blue-400 uppercase tracking-wider mb-2">
            Why this cannot be waived
          </p>
          <p className="text-sm text-blue-100 leading-relaxed">{remediation.explanation}</p>
        </div>

        {/* Hypothetical change suggestion */}
        {remediation.hypothetical_change && (
          <div className="rounded-lg bg-neutral-800 border border-neutral-700 p-3">
            <p className="text-xs font-semibold text-neutral-400 uppercase tracking-wider mb-2">
              What policy change would allow this?
            </p>
            <p className="text-sm text-neutral-200 leading-relaxed">
              {remediation.hypothetical_change}
            </p>
          </div>
        )}

        {/* Simulate button */}
        <button
          onClick={() =>
            remediation.hypothetical_change &&
            onSwitchToSimulate(remediation.hypothetical_change)
          }
          className="w-full px-4 py-2.5 border border-blue-700 bg-blue-900 hover:bg-blue-800 rounded-lg text-sm text-blue-200 font-medium transition-colors flex items-center justify-center gap-2"
        >
          <span>⚡</span>
          <span>Run What-If Simulation</span>
        </button>
      </div>
    </div>
  )
}
