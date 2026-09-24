'use client'

import React, { useState } from 'react'
import { Save } from 'lucide-react'
import { Modal } from './Modal'

export interface SaveModalProps {
  open: boolean
  onClose: () => void
  companyName: string
  scenario: string
  onSave: (name: string) => Promise<void>
}

export function SaveModal({
  open,
  onClose,
  companyName,
  scenario,
  onSave,
}: SaveModalProps) {
  const defaultName = `${companyName || 'Model'} – ${scenario.toUpperCase()} – ${new Date().toISOString().slice(0, 10)}`
  const [name, setName] = useState(defaultName)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return

    setSaving(true)
    setError(null)
    try {
      await onSave(name.trim())
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed')
      setSaving(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Save Valuation Model">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="save-model-name" className="block text-[12px] font-semibold text-text-muted mb-1.5">
            Model Name
          </label>
          <input
            id="save-model-name"
            name="model-name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={saving}
            data-autofocus
            className="w-full h-9 bg-surface-3 border border-border-interactive rounded-sm px-3 text-[13px] text-text-main placeholder:text-text-faint transition-colors"
            placeholder="e.g. Infosys — bull case, higher margins"
          />
        </div>

        {error && (
          <div
            role="alert"
            aria-live="assertive"
            className="text-[11px] text-[#ef4444] font-semibold bg-[#ef4444]/10 border border-[#ef4444]/20 rounded-[3px] p-2"
          >
            {error}
          </div>
        )}

        <div className="flex items-center justify-end space-x-2 pt-2 border-t border-[#1e283d]">
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="px-4 py-1.5 bg-[#192030] hover:bg-[#2a3652] text-[#94a3b8] hover:text-[#f8fafc] border border-[#1e283d] rounded-[4px] text-[12px] font-semibold transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={saving || !name.trim()}
            className="flex items-center space-x-1.5 px-4 py-1.5 bg-[#0ea5e9] hover:bg-[#38bdf8] text-white rounded-[4px] text-[12px] font-semibold transition-colors disabled:opacity-50"
          >
            <Save className="w-3.5 h-3.5" />
            <span>{saving ? 'Saving...' : 'Save Model'}</span>
          </button>
        </div>
      </form>
    </Modal>
  )
}
