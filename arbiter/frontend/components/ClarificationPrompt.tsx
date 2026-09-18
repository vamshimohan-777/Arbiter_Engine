'use client'
import type { ClarificationRequest } from '@/lib/types'

export default function ClarificationPrompt({
  clarification,
  onSelectOption,
}: {
  clarification: ClarificationRequest
  onSelectOption?: (field: string, value: string) => void
}) {
  return (
    <div className="rounded-xl bg-yellow-950 border border-yellow-700 p-4">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-yellow-400 font-bold text-lg">?</span>
        <span className="text-sm font-semibold text-yellow-300">
          Clarification needed
        </span>
      </div>

      <p className="text-sm text-yellow-200 leading-relaxed mb-3">
        {clarification.reason}
      </p>

      {clarification.missing_fields.length > 0 && (
        <div className="space-y-3">
          <p className="text-xs text-yellow-500 uppercase tracking-wider font-semibold">
            Missing context
          </p>
          {clarification.missing_fields.map((field) => (
            <div key={field}>
              <span className="inline-block text-xs font-mono text-yellow-300 bg-yellow-900 border border-yellow-700 px-2 py-0.5 rounded capitalize mb-1">
                {field}
              </span>
              {clarification.suggested_options[field] && (
                <div className="flex flex-wrap gap-1 mt-1">
                  {clarification.suggested_options[field].map((opt) => (
                    <button
                      key={opt}
                      onClick={() => onSelectOption?.(field, opt)}
                      className="text-xs px-2 py-0.5 bg-yellow-900 hover:bg-yellow-700 active:bg-yellow-600 text-yellow-200 rounded border border-yellow-700 hover:border-yellow-500 transition-colors cursor-pointer"
                    >
                      {opt}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <p className="text-xs text-yellow-600 mt-3">
        Click an option above or type the missing context in the Context panel, then ask again.
      </p>
    </div>
  )
}
