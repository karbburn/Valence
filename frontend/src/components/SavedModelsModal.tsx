'use client'

import React, { useState, useEffect, useCallback } from 'react'
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
  const [models, setModels] = useState<SavedModelHeader[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)

  const loadList = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchSavedModels()
      setModels(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch saved models')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open) {
      loadList()
      setConfirmDeleteId(null)
    }
  }, [open, loadList])

  const handleDelete = async (modelId: string) => {
    setDeletingId(modelId)
    try {
      await deleteSavedModel(modelId)
      setModels((prev) => prev.filter((m) => m.model_id !== modelId))
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
      title="Saved Valuation Models"
      maxWidth="max-w-2xl"
    >
      <div className="space-y-4">
        {error && (
          <div className="flex items-center space-x-2 text-[11px] text-[#ef4444] font-semibold bg-[#ef4444]/10 border border-[#ef4444]/20 rounded-[3px] p-2.5">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Model List */}
        <div className="space-y-2.5 max-h-[420px] overflow-y-auto pr-1">
          {loading ? (
            <div className="text-center py-8 text-[12px] text-[#94a3b8]">
              Loading saved models...
            </div>
          ) : models.length === 0 ? (
            <div className="text-center py-8 text-[12px] text-[#64748b]">
              No saved models found. Save your current model to access it here.
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
                  <div className="flex items-center space-x-3 text-[11px] text-[#64748b]">
                    <span className="flex items-center space-x-1">
                      <Building2 className="w-3 h-3 text-[#94a3b8]" />
                      <span className="font-mono text-[#94a3b8]">{m.company_id}</span>
                    </span>
                    <span>·</span>
                    <span className="flex items-center space-x-1">
                      <Clock className="w-3 h-3 text-[#64748b]" />
                      <span>{new Date(m.created_at).toLocaleDateString()}</span>
                    </span>
                  </div>
                </div>

                {/* Actions */}
                <div className="flex items-center space-x-2 shrink-0">
                  {confirmDeleteId === m.model_id ? (
                    <div className="flex items-center space-x-1.5 bg-[#ef4444]/10 border border-[#ef4444]/30 rounded-[4px] px-2 py-1">
                      <span className="text-[11px] font-semibold text-[#ef4444]">
                        Delete?
                      </span>
                      <button
                        onClick={() => handleDelete(m.model_id)}
                        disabled={deletingId === m.model_id}
                        className="px-2 py-0.5 bg-[#ef4444] text-white text-[10px] font-bold rounded-[2px] hover:bg-[#dc2626]"
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
                        className="p-1.5 text-[#64748b] hover:text-[#ef4444] border border-[#1e283d] rounded-[4px] hover:border-[#ef4444]/30 hover:bg-[#ef4444]/10 transition-colors"
                        title="Delete model"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
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
