/**
 * Why a ticker has no model, in the visitor's terms.
 *
 * Split out of `api.ts` so it can be tested. This is the copy a reader sees at the moment
 * they decide whether to trust anything else on the page, which makes it the one place a
 * product like this is most entitled to mislead them, and it had no test at all.
 *
 * 503 means the engine could not compile this company right now. It is NOT a verdict on the
 * company. The causes are "we could not source the filings" and "we could not reach the
 * providers", and the copy must not pick one, because from the outside they look identical.
 *
 * The original wording picked one, and picked the wrong one. It said "no annual filings
 * could be reached for it, so there is nothing to model" -- a factual claim about a company
 * we know nothing about. Adani Green files annually with its exchange, and the page failed
 * because a fetch did not come back. The sentence told a reader the company has no
 * financials when the truth was that we had not asked successfully.
 *
 * It also printed the internal storage key, uppercased: ADANIGREEN_ADANIGREEN. That is
 * plumbing, not a name, and putting it in front of a visitor tells them the system is
 * showing them its internals. The ticker is what a person recognises.
 *
 * The fix for the first problem introduced a second one. It ended "The company does file,
 * so this is most likely a temporary failure to reach them", which is a different unverified
 * claim in the opposite direction: for a ticker the engine genuinely could not source,
 * nothing here knows whether the company files at all. It was asserted to every visitor on
 * the strength of a guess, and the backend had been recording genuine defects into the same
 * cached state for five minutes at a time, so the guess was being made about companies
 * whose build had crashed.
 *
 * So the sentence says what is actually true, and stops there: we did not produce a model,
 * and that is a statement about us rather than about the filer.
 *
 * An earlier draft of that sentence read "no model was produced, which is not the same as
 * the company having nothing to report". The test written alongside it failed on its own
 * copy, because "having nothing to report" is a claim about the filer wearing a
 * disclaimer, and it is the same error in the opposite direction. The clause bought nothing
 * that "that is a statement about this engine, not about the company" does not already say.
 */
/**
 * The label a visitor should recognise, from a company id.
 *
 * `infy_infy` is the storage key and `INFY` is what a person knows the company as. The key
 * was once printed on screen uppercased, which put a JSON field name in front of a reader
 * and told them the system was showing them its plumbing.
 *
 * KNOWN LIMIT, recorded rather than smoothed over: this takes the first underscore-delimited
 * token, which is right for the id shape the engine actually builds (`bhartiartl_bhartiartl`,
 * `tatamotors_tatamotors`) and wrong for a company whose own name contains an underscore,
 * where `adani_green_adani_green` yields `ADANI`. Deriving the real ticker means asking the
 * universe registry, which the error path does not have. So the label can be a prefix of the
 * company rather than its ticker, and that is better than the storage key and not as good as
 * the exchange's name. It affects only the error page for a company with no model.
 */
export function tickerLabelFrom(companyId: string): string {
  return companyId.split('_')[0]?.trim().toUpperCase() ?? ''
}

export function unavailableMessage(ticker: string, detail: string): string {
  const label = ticker.trim().toUpperCase()
  // The API leads with the reason in its own words, which only repeats what follows.
  // Dropped so one sentence carries it all. Both forms are stripped, because the backend
  // now distinguishes them and this copy must not read as though it did not.
  const tail = detail
    .replace(/^\s*No financial statements could be sourced[^.]*\.\s*/i, '')
    .replace(/^\s*The filing providers could not be reached[^.]*\.\s*/i, '')
    .replace(/\s*Try again shortly\.?\s*$/i, '')
    .trim()
  return (
    `${label}: ${tail || 'the filings behind this company could not be reached'}. ` +
    'That is a statement about this engine right now, not about the company. ' +
    'Try again in a few minutes.'
  )
}
