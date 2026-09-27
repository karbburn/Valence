'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { QuickDCFView } from '@/components/QuickDCFView'
import type { ModelSpecification, ScenarioLabel } from '@/lib/types'

/**
 * The live model, mounted for real.
 *
 * A screenshot of a valuation tool is a claim. This is the actual component,
 * running against an actual fetched specification, with the scenario switch
 * wired up. Nothing here is a div-built imitation of an interface.
 *
 * The methodology link is deferred to the public page rather than opening the
 * in-app modal, because a marketing page that opens a modal cannot be shared or
 * indexed and the methodology deserves a real URL.
 */
export function LiveModelPreview({ spec }: { spec: ModelSpecification }) {
  const [scenario, setScenario] = useState<ScenarioLabel>('base')
  const router = useRouter()

  return (
    <div className="border border-border rounded-sm bg-canvas overflow-hidden">
      <div className="flex items-center justify-between gap-3 px-3.5 py-2.5 border-b border-border bg-surface-2/60">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className="font-mono text-[11px] font-bold text-accent-hover bg-accent-subtle border border-accent-border rounded-sm px-1.5 py-0.5">
            {spec.metadata?.ticker}
          </span>
          <span className="text-[12.5px] text-text-main truncate">{spec.metadata?.name}</span>
        </div>

        <div
          role="radiogroup"
          aria-label="Valuation scenario"
          className="flex items-center gap-0.5 shrink-0 p-0.5 bg-surface border border-border rounded-sm"
        >
          {(['base', 'bull', 'bear'] as ScenarioLabel[]).map((s) => (
            <button
              key={s}
              type="button"
              role="radio"
              aria-checked={scenario === s}
              onClick={() => setScenario(s)}
              className={`px-2 py-0.5 text-[11px] capitalize rounded-sm transition-colors cursor-pointer ${
                scenario === s
                  ? 'bg-surface-2 text-text-main font-semibold'
                  : 'text-text-dim hover:text-text-muted'
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      <div className="p-3.5 sm:p-4">
        <QuickDCFView
          spec={spec}
          scenario={scenario}
          onOpenMethodology={() => router.push('/methodology')}
          // The landing page is a proof, not a workstation. The sensitivity
          // matrix is the tallest thing in here and the least useful without
          // the rest of the workbench, so it stays on the ticker page only.
          compact
        />
      </div>

      <div className="px-3.5 py-2.5 border-t border-border bg-surface-2/40 flex items-center justify-between gap-3">
        <span className="text-[11px] text-text-dim font-mono">
          Live component, real specification
        </span>
        <Link
          href="/stock"
          className="text-[11.5px] text-accent hover:text-accent-hover transition-colors"
        >
          Open the full workbench
        </Link>
      </div>
    </div>
  )
}
