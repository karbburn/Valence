/**
 * Copy for the OpenGraph share card.
 *
 * Split out of the route so it can be tested. The card is 1200x630 with a fixed layout
 * and no scrolling, so text that runs long does not degrade, it overflows the frame, and
 * an overflowing card cannot be seen from the source that produced it.
 */

/** Room for roughly three lines at the card's font size. */
const REASON_BUDGET = 190

/**
 * The withheld reason, cut to what fits a card.
 *
 * Two failures are worth naming, because the first version had both. It returned the whole
 * paragraph whenever the check name appeared in the first 60 characters, so the served
 * /stock/INFY card ran its reason through the footer and off the bottom edge; and it had
 * no length cap at all, so the longest reason in the catalogue would have done the same to
 * any company.
 *
 * What must survive the cut is the NAME of the check that stopped publication. "The engine
 * could not verify the inputs to this model" and "inputs_trace_to_a_filing" tell a reader
 * deciding whether to trust the rest of the site entirely different things, and only the
 * second names something they can check. The full text is on the page and in the meta
 * description.
 */
export function ogCardReason(reason: string | undefined): string {
  if (!reason) return 'The engine could not verify the inputs to this model.'

  const first = (reason.split('\n\n')[0] ?? '').trim()
  const colon = first.indexOf(': ')
  const hasCheck = colon > 0 && colon < 60
  const check = hasCheck ? first.slice(0, colon) : ''
  const body = hasCheck ? first.slice(colon + 2) : first

  // The first sentence after the check name, which is the finding itself rather than the
  // elaboration that follows it.
  const sentence = (body.split(/(?<=\.)\s/)[0] ?? body).trim()
  const cut =
    sentence.length > REASON_BUDGET
      ? `${sentence.slice(0, REASON_BUDGET).trimEnd()}...`
      : sentence
  return check ? `${check}: ${cut}` : cut
}
