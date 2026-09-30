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

import type {
  ModelCheckResult,
  ModelSpecWithVerdict,
  ModelSpecification,
  PublicationVerdict,
} from './types'

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
  // Read it off the spec when the caller did not pass it. `ModelSpecWithVerdict`
  // extends `ModelSpecification`, so a component typed against the base still
  // receives the field at runtime -- which means no call site has to thread a prop
  // to get the server's answer, and no call site can forget.
  const serverVerdict = verdict ?? (spec as ModelSpecWithVerdict | null)?.publication
  if (serverVerdict) return serverVerdict.publishable

  // No verdict to read. This is the path a client fetch takes when the payload was
  // cast to a bare spec, and it is the path the divergence lived on: the previous
  // fallback listed five defect-check names, the server had eight, and any model
  // failing only a newer check had its price published while the API returned
  // opinion_only.
  //
  // So the fallback refuses rather than guessing from a subset. A headline is a
  // claim about a figure, and a partial list of reasons is not evidence for it.
  // The cost is that a caller who drops the verdict shows n/a on a perfectly good
  // model, which is a visible, fixable mistake rather than a wrong number.
  return false
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
  const serverVerdict = verdict ?? (spec as ModelSpecWithVerdict | null)?.publication
  if (serverVerdict?.reasons?.length) return serverVerdict.reasons.join('\n\n')
  if (serverVerdict?.input_defect_checks_failed?.length) {
    return `The engine could not verify: ${serverVerdict.input_defect_checks_failed.join(', ')}.`
  }
  const failed = (spec?.qa?.checks ?? []).filter((c) => !c.passed)
  return (
    failed.map((c) => `${c.check_name}: ${c.detail}`).join('\n\n') ||
    'The engine could not verify the inputs to this model.'
  )
}
