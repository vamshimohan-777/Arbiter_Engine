'use client'

import { useState, useEffect } from 'react'
import type { SimulationChange } from '@/lib/types'

const CHANGE_TYPES = [
  { value: 'REMOVE_EXCEPTION', label: 'Remove Exception / Prohibition' },
  { value: 'ADD_EXCEPTION', label: 'Add Exception / Permit' },
  { value: 'MODIFY_RULE', label: 'Modify Rule Text' },
  { value: 'REMOVE_POLICY', label: 'Remove Policy Entirely' },
  { value: 'ADD_POLICY', label: 'Add New Policy' },
]

interface Props {
  initialChange?: SimulationChange | null
  onSimulate: (change: SimulationChange, testQuestions?: string[]) => void
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
      undefined
    )
  }

  return (
    <div className="glass-panel mx-auto max-w-3xl rounded-[28px] border border-blue-100 p-6">
      <div className="flex items-center gap-2 mb-4">
        <span className="text-blue-600">⚡</span>
        <h3 className="text-sm font-semibold text-slate-800">What-If Simulation</h3>
        <span className="ml-auto text-xs text-slate-500">Does not modify real policies</span>
      </div>

      <div className="space-y-3">
        <div>
          <label className="mb-1 block text-xs font-semibold text-slate-600">Change type</label>
          <select
            value={changeType}
            onChange={(e) => setChangeType(e.target.value)}
            className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 outline-none focus:border-blue-400"
          >
            {CHANGE_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="mb-1 block text-xs font-semibold text-slate-600">
            Description <span className="text-slate-400">(required)</span>
          </label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Describe the hypothetical policy action"
            rows={3}
            className="w-full resize-none rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 outline-none placeholder:text-slate-400 focus:border-blue-400"
          />
        </div>

        <div>
          <label className="mb-1 block text-xs font-semibold text-slate-600">
            Target policy ID <span className="text-slate-400">(optional)</span>
          </label>
          <input
            type="text"
            value={targetPolicyId}
            onChange={(e) => setTargetPolicyId(e.target.value)}
            placeholder="Policy identifier"
            className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 outline-none placeholder:text-slate-400 focus:border-blue-400"
          />
        </div>

        {(changeType === 'ADD_EXCEPTION' || changeType === 'MODIFY_RULE' || changeType === 'ADD_POLICY') && (
          <div>
            <label className="mb-1 block text-xs font-semibold text-slate-600">
              New rule / exception text
            </label>
            <textarea
              value={newText}
              onChange={(e) => setNewText(e.target.value)}
              placeholder="Enter the proposed policy wording"
              rows={3}
              className="w-full resize-none rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 outline-none placeholder:text-slate-400 focus:border-blue-400"
            />
          </div>
        )}

        <p className="text-xs leading-relaxed text-slate-500">
          Simulation evaluates relevant historical rulings; it never changes the loaded policy corpus.
        </p>

        <button
          onClick={handleSubmit}
          disabled={isLoading || !description.trim()}
          className="w-full rounded-xl bg-gradient-to-r from-blue-600 to-teal-500 py-2.5 text-sm font-semibold text-white shadow-md shadow-blue-200 transition hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isLoading ? 'Running simulation…' : 'Run Simulation'}
        </button>
      </div>
    </div>
  )
}
