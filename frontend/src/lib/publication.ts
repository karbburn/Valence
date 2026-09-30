/**
 * Whether a model may be presented as a valuation.
 *
 * This used to be recomputed here from a hardcoded copy of the defect-check names,
 * five of them, while the backend's `_INPUT_DEFECT_CHECKS` held eight. The two
 * lists had already diverged: `valuation_is_meaningful` and `debt_is_actually_sourced`
 * existed on the server and not here. It happened to work for the companies that
 * failed several checks at once, and would have shown a negative share price for
 * one that failed only the newest check.
 *
 * That is the fifth time in this project a hand-kept table has fallen behind the
 * authority it copies -- after CIK_REGISTRY, the metadata registry, the revenue
 * tag list, and the second copy of those tags one function below the first.
 *
 * The server already decides this, in `_publication_verdict`, and returns it on
 * every payload. Two answers about the same question is one too many, so the
 * verdict is read rather than recomputed. If the rule changes, it changes in one
 * place and the page follows.
 */

import type { ModelCheckResult, ModelSpecification, PublicationVerdict } from './types'

/**
 * The server's verdict, when the payload carries one.
 *
 * `undefined` means the caller is holding a bare spec with no verdict attached,
 * which happens in tests and in the Excel/JSON paths. Returning undefined rather
 * than a default keeps that case visible instead of silently reading as
 * publishable.
 */
export function publicationVerdict(
  payload: { publication?: PublicationVerdict } | null | undefined,
): PublicationVerdict | undefined {
  return payload?.publication
}

/**
 * Whether the implied share price may be shown as a valuation.
 *
 * Falls back to the QA checks only when no verdict was supplied, so a caller with
 * a bare spec still gets an answer rather than an unconditional pass.
 */
export function mayPublishPrice(
  spec: ModelSpecification | null | undefined,
  verdict?: PublicationVerdict,
): boolean {
  if (verdict) return verdict.publishable
  const checks: ModelCheckResult[] = spec?.qa?.checks ?? []
  if (!checks.length) return false
  // With no verdict to read, the conservative answer is not to publish. A
  // headline that shows a number is a claim; the absence of evidence is not
  // evidence of a number.
  return !checks.some((c) => c.check_name === 'valuation_is_meaningful' && !c.passed)
}

/**
 * The tooltip explaining why a price is withheld, built from whatever failed.
 *
 * Returns undefined when the model is publishable, so callers can omit the title
 * rather than show an empty one.
 */
export function withheldReason(
  spec: ModelSpecification | null | undefined,
  verdict?: PublicationVerdict,
): string | undefined {
  if (mayPublishPrice(spec, verdict)) return undefined
  const failed = (spec?.qa?.checks ?? []).filter((c) => !c.passed)
  return (
    failed.map((c) => `${c.check_name}: ${c.detail}`).join('\n\n') ||
    'The engine could not verify the inputs to this model.'
  )
}
