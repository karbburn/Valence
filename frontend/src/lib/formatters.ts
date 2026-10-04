// Single consistent formatter suite for financial and UI data

/**
 * The mark a figure's cell carries when the engine produced none.
 *
 * A bare dash is the old convention and it is wrong here for a specific reason rather than
 * a stylistic one. These are financial tables, so a horizontal stroke already means a
 * negative number: -5.0% and "no figure at all" were both a dash, in the same column, at the
 * same size. A reader scanning for downside could not tell a loss from a gap, and a screen
 * reader announced the same word for both.
 *
 * "n/a" is unambiguous in both channels and says what is true, which is that the engine
 * declined to produce a figure rather than that the figure is zero. Every cell using it is a
 * cell where a reader needs exactly that distinction.
 *
 * It lives here rather than in `noValue.ts` because it is a FORMATTING decision and this
 * module has to be able to apply it. The four formatters below used to return an em-dash
 * while 30 call sites passed `NO_VALUE` themselves, so the codebase carried both marks for
 * one fact and which one appeared depended on which component asked. `noValue.ts` re-exports
 * this, so every existing import keeps working and there is still one answer.
 *
 * The direction of the dependency is deliberate: a leaf constant that a formatter cannot
 * import is a constant the formatter will drift away from again.
 */
export const NO_VALUE = 'n/a'

export function getCurrencySymbol(currency: string): string {
  return currency === 'USD' ? '$' : '₹'
}

export function getCurrencyUnit(currency: string): string {
  return currency === 'USD' ? 'USD M' : 'INR Cr'
}

export function fmtNum(val: number | null | undefined, decimals = 0): string {
  if (val == null || isNaN(val)) return NO_VALUE
  return val.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

export function fmtPrice(val: number | null | undefined, currency = 'INR', decimals = 2): string {
  if (val == null || isNaN(val)) return NO_VALUE
  const sym = getCurrencySymbol(currency)
  const abs = Math.abs(val)
  const sign = val < 0 ? '-' : ''
  return `${sign}${sym}${fmtNum(abs, decimals)}`
}

export function fmtMoney(val: number | null | undefined, currency = 'INR'): string {
  if (val == null || isNaN(val)) return NO_VALUE
  const sym = getCurrencySymbol(currency)
  const abs = Math.abs(val)
  const sign = val < 0 ? '-' : ''

  if (currency === 'USD') {
    if (abs >= 1e6) return `${sign}${sym}${(abs / 1e6).toFixed(2)}T`
    if (abs >= 1e3) return `${sign}${sym}${(abs / 1e3).toFixed(1)}B`
    return `${sign}${sym}${fmtNum(abs)}M`
  }

  // INR Crores
  if (abs >= 1e5) return `${sign}${sym}${(abs / 1e5).toFixed(2)}L Cr`
  return `${sign}${sym}${fmtNum(abs)} Cr`
}

export function fmtPct(val: number | null | undefined, decimals = 2): string {
  if (val == null || isNaN(val)) return NO_VALUE
  return `${val.toFixed(decimals)}%`
}
