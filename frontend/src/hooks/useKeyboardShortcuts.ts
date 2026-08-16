'use client'

import { useEffect } from 'react'
import { ScenarioLabel } from '@/lib/types'

export interface KeyboardShortcutsConfig {
  onSave?: () => void
  onSetMode?: (mode: 'analyst' | 'quick' | 'full') => void
  onScenarioChange?: (scenario: ScenarioLabel) => void
  onCloseModals?: () => void
  currentScenario?: ScenarioLabel
  hasOpenModal?: boolean
}

const SCENARIOS: ScenarioLabel[] = ['base', 'bull', 'bear']

export function useKeyboardShortcuts({
  onSave,
  onSetMode,
  onScenarioChange,
  onCloseModals,
  currentScenario = 'base',
  hasOpenModal = false,
}: KeyboardShortcutsConfig) {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Check if user is typing inside an input element
      const activeEl = document.activeElement
      const isInput =
        activeEl instanceof HTMLInputElement ||
        activeEl instanceof HTMLTextAreaElement ||
        activeEl instanceof HTMLSelectElement ||
        activeEl?.getAttribute('contenteditable') === 'true'

      // Ctrl+S / Cmd+S: Save Model (always intercepted)
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault()
        onSave?.()
        return
      }

      // Escape: Close modals
      if (e.key === 'Escape') {
        onCloseModals?.()
        return
      }

      // If typing inside an input field, do not trigger single-key navigation shortcuts
      if (isInput) return

      // Mode Switching: 1, 2, 3
      if (e.key === '1') {
        e.preventDefault()
        onSetMode?.('analyst')
      } else if (e.key === '2') {
        e.preventDefault()
        onSetMode?.('quick')
      } else if (e.key === '3') {
        e.preventDefault()
        onSetMode?.('full')
      }

      // Scenario Navigation: ArrowLeft / ArrowRight
      if (!hasOpenModal && onScenarioChange) {
        const currentIndex = SCENARIOS.indexOf(currentScenario)
        if (e.key === 'ArrowLeft') {
          e.preventDefault()
          const nextIndex = (currentIndex - 1 + SCENARIOS.length) % SCENARIOS.length
          onScenarioChange(SCENARIOS[nextIndex])
        } else if (e.key === 'ArrowRight') {
          e.preventDefault()
          const nextIndex = (currentIndex + 1) % SCENARIOS.length
          onScenarioChange(SCENARIOS[nextIndex])
        }
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [
    onSave,
    onSetMode,
    onScenarioChange,
    onCloseModals,
    currentScenario,
    hasOpenModal,
  ])
}
