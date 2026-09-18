'use client'

import { useState, useEffect } from 'react'
import type { SimulationChange } from '@/lib/types'

// Default questions always sent so simulation always has something to test
const DEFAULT_TEST_QUESTIONS = [
  'Can Analytics share Dataset Y with Vendor X in India today?',
  'Can Engineering share Dataset Y with Vendor X for testing?',
  'Can Analytics share Dataset Y with Vendor Y in the EU?',
  'Can Finance share Dataset W with Vendor Z?',
  'Can Analytics share Dataset Z with Vendor Y?',
]

const CHANGE_TYPES = [
  { value: 'REMOVE_EXCEPTION', label: 'Remove Exception / Prohibition' },
  { value: 'ADD_EXCEPTION', label: 'Add Exception / Permit' },
  { value: 'MODIFY_RULE', label: 'Modify Rule Text' },
  { value: 'REMOVE_POLICY', label: 'Remove Policy Entirely' },
  { value: 'ADD_POLICY', label: 'Add New Policy' },
]

interface Props {
  initialChange?: SimulationChange | null
  onSimulate: (change: SimulationChange, testQuestions: string[]) => void
  isLoading: boolean
}

export default function SimulatePanel({ initialChange, onSimulate, isLoading }: Props) {
  const [changeType, setChangeType] = useState(
    initialChange?.change_type ?? 'REMOVE_EXCEPTION'
  )
  const [description, setDescription] = useState(initialChange?.description ?? '')
  const [targetPolicyId, setTargetPolicyId] = useState(
    initialChange?.target_policy_id ?? ''
  )
  const [newText, setNewText] = useState(initialChange?.new_text ?? '')

  useEffect(() => {
    if (initialChange) {
      setChangeType(initialChange.change_type)
      setDescription(initialChange.description)
      setTargetPolicyId(initialChange.target_policy_id ?? '')
      setNewText(initialChange.new_text ?? '')
    }
  }, [initialChange])

  const handleSubmit = () => {
    if (!description.trim()) return
    onSimulate(
      {
        change_type: changeType,
        description: description.trim(),
        target_policy_id: targetPolicyId.trim() || undefined,
        new_text: newText.trim() || undefined,
      },
      DEFAULT_TEST_QUESTIONS
    )
  }

  return (
    <div className="bg-blue-950 border border-blue-800 rounded-xl p-5 mb-4">
      <div className="flex items-center gap-2 mb-4">
        <span className="text-blue-400">⚡</span>
        <h3 className="text-sm font-semibold text-blue-300">What-If Simulation</h3>
        <span className="ml-auto text-xs text-blue-700">Does NOT modify real policies</span>
      </div>

      <div className="space-y-3">
        <div>
          <label className="block text-xs text-blue-400 mb-1">Change Type</label>
          <select
            value={changeType}
            onChange={(e) => setChangeType(e.target.value)}
            className="w-full px-3 py-2 bg-neutral-800 border border-neutral-700 rounded-lg text-sm text-neutral-200 focus:outline-none focus:border-blue-600"
          >
            {CHANGE_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs text-blue-400 mb-1">
            Description <span className="text-blue-700">(required)</span>
          </label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="e.g. Remove the Vendor X restriction from DS-001-v5 Section S2"
            rows={3}
            className="w-full px-3 py-2 bg-neutral-800 border border-neutral-700 rounded-lg text-sm text-neutral-200 placeholder-neutral-600 focus:outline-none focus:border-blue-600 resize-none"
          />
        </div>

        <div>
          <label className="block text-xs text-blue-400 mb-1">
            Target Policy ID <span className="text-blue-700">(optional)</span>
          </label>
          <input
            type="text"
            value={targetPolicyId}
            onChange={(e) => setTargetPolicyId(e.target.value)}
            placeholder="e.g. DS-001-v5"
            className="w-full px-3 py-2 bg-neutral-800 border border-neutral-700 rounded-lg text-sm text-neutral-200 placeholder-neutral-600 focus:outline-none focus:border-blue-600"
          />
        </div>

        {(changeType === 'ADD_EXCEPTION' || changeType === 'MODIFY_RULE' || changeType === 'ADD_POLICY') && (
          <div>
            <label className="block text-xs text-blue-400 mb-1">
              New Rule / Exception Text
            </label>
            <textarea
              value={newText}
              onChange={(e) => setNewText(e.target.value)}
              placeholder="Text of the new rule or exception clause..."
              rows={3}
              className="w-full px-3 py-2 bg-neutral-800 border border-neutral-700 rounded-lg text-sm text-neutral-200 placeholder-neutral-600 focus:outline-none focus:border-blue-600 resize-none"
            />
          </div>
        )}

        <p className="text-xs text-blue-800">
          Will test against {DEFAULT_TEST_QUESTIONS.length} standard policy questions
        </p>

        <button
          onClick={handleSubmit}
          disabled={isLoading || !description.trim()}
          className="w-full py-2.5 bg-blue-700 hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-sm text-white font-medium transition-colors"
        >
          {isLoading ? 'Running simulation…' : 'Run Simulation'}
        </button>
      </div>
    </div>
  )
}
