'use client'

import React, { useState, useEffect } from 'react'
import { FolderOpen, Trash2, Clock, Building2, AlertCircle } from 'lucide-react'
import { SavedModelHeader } from '@/lib/types'
import { fetchSavedModels, deleteSavedModel } from '@/lib/api'
import { Modal } from './Modal'

export interface SavedModelsModalProps {
  open: boolean
  onClose: () => void
  onLoadModel: (modelId: string) => Promise<void>
}

export function SavedModelsModal({
  open,
  onClose,
  onLoadModel,
}: SavedModelsModalProps) {
  const [models, setModels] = useState<SavedModelHeader[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)

  // The modal mounts only while open, so a mount-effect is the natural load point.
  // All state updates happen after the async boundary, never synchronously.
  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const data = await fetchSavedModels()
        if (alive) setModels(data)
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : 'Failed to fetch saved models')
      }
    })()
    return () => {
      alive = false
    }
  }, [])

  const handleDelete = async (modelId: string) => {
    setDeletingId(modelId)
    try {
      await deleteSavedModel(modelId)
      setModels((prev) => (prev ? prev.filter((m) => m.model_id !== modelId) : prev))
      setConfirmDeleteId(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed')
    } finally {
      setDeletingId(null)
    }
  }

  const handleSelectModel = async (modelId: string) => {
    try {
      await onLoadModel(modelId)
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load model')
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Model Library: Saved Valuations"
      maxWidth="max-w-2xl"
    >
      <div className="space-y-4">
        {error && (
          <div
            role="alert"
            aria-live="assertive"
            className="flex items-center space-x-2 text-[11px] text-negative font-semibold bg-negative-subtle border border-negative rounded-[3px] p-2.5"
          >
            <AlertCircle className="w-4 h-4 shrink-0" aria-hidden />
            <span>{error}</span>
          </div>
        )}

        {/* Model List */}
        <div className="space-y-2.5 max-h-[420px] overflow-y-auto pr-1" role="status" aria-busy={models === null}>
          {models === null ? (
            <div className="text-center py-8 text-[12px] text-text-muted">
              Loading saved models…
            </div>
          ) : models.length === 0 ? (
            <div className="text-center py-8 text-[12px] text-text-dim space-y-1.5">
              <p>No saved models yet.</p>
              <p className="text-text-faint">
                Press <kbd>Ctrl S</kbd> to save the current view and find it here.
              </p>
            </div>
          ) : (
            models.map((m) => (
              <div
                key={m.model_id}
                className="bg-[#080c14] border border-[#1e283d] rounded-[4px] p-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 hover:border-[#2a3652] transition-colors"
              >
                <div className="space-y-1 min-w-0">
                  <h4 className="font-semibold text-[13px] text-[#f8fafc] truncate">
                    {m.name}
                  </h4>
                  <div className="flex items-center space-x-3 text-[11px] text-text-dim">
                    <span className="flex items-center space-x-1">
                      <Building2 className="w-3 h-3 text-[#94a3b8]" />
                      <span className="font-mono text-[#94a3b8]">{m.company_id}</span>
                    </span>
                    <span>·</span>
                    <span className="flex items-center space-x-1">
                      <Clock className="w-3 h-3 text-text-dim" />
                      <span>{new Date(m.created_at).toLocaleDateString()}</span>
                    </span>
                  </div>
                </div>

                {/* Actions */}
                <div className="flex items-center space-x-2 shrink-0">
                  {confirmDeleteId === m.model_id ? (
                    <div className="flex items-center space-x-1.5 bg-negative-subtle border border-negative rounded-[4px] px-2 py-1">
                      <span className="text-[11px] font-semibold text-negative">
                        Delete?
                      </span>
                      <button
                        onClick={() => handleDelete(m.model_id)}
                        disabled={deletingId === m.model_id}
                        className="px-2 py-0.5 bg-negative-subtle text-white text-[10px] font-bold rounded-[2px] hover:bg-negative-subtle"
                      >
                        {deletingId === m.model_id ? '...' : 'Yes'}
                      </button>
                      <button
                        onClick={() => setConfirmDeleteId(null)}
                        className="px-2 py-0.5 bg-[#192030] text-[#94a3b8] text-[10px] font-bold rounded-[2px] hover:text-[#f8fafc]"
                      >
                        No
                      </button>
                    </div>
                  ) : (
                    <>
                      <button
                        onClick={() => handleSelectModel(m.model_id)}
                        className="flex items-center space-x-1 px-3 py-1 bg-[#0ea5e9] hover:bg-[#38bdf8] text-white text-[12px] font-semibold rounded-[4px] transition-colors"
                      >
                        <FolderOpen className="w-3.5 h-3.5" />
                        <span>Load</span>
                      </button>
                      <button
                        onClick={() => setConfirmDeleteId(m.model_id)}
                        className="p-1.5 text-text-dim hover:text-negative border border-[#1e283d] rounded-[4px] hover:border-negative hover:bg-negative-subtle transition-colors"
                        title="Delete model"
                        aria-label={`Delete ${m.name}`}
                      >
                        <Trash2 className="w-3.5 h-3.5" aria-hidden />
                      </button>
                    </>
                  )}
                </div>
              </div>
            ))
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end pt-2 border-t border-[#1e283d]">
          <button
            onClick={onClose}
            className="px-4 py-1.5 bg-[#192030] hover:bg-[#2a3652] text-[#94a3b8] hover:text-[#f8fafc] border border-[#1e283d] rounded-[4px] text-[12px] font-semibold transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </Modal>
  )
}
