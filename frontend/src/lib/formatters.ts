// Single consistent formatter suite for financial and UI data

export function getCurrencySymbol(currency: string): string {
  return currency === 'USD' ? '$' : '₹'
}

export function getCurrencyUnit(currency: string): string {
  return currency === 'USD' ? 'USD M' : 'INR Cr'
}

export function fmtNum(val: number | null | undefined, decimals = 0): string {
  if (val == null || isNaN(val)) return '—'
  return val.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

export function fmtPrice(val: number | null | undefined, currency = 'INR', decimals = 2): string {
  if (val == null || isNaN(val)) return '—'
  const sym = getCurrencySymbol(currency)
  const abs = Math.abs(val)
  const sign = val < 0 ? '-' : ''
  return `${sign}${sym}${fmtNum(abs, decimals)}`
}

export function fmtMoney(val: number | null | undefined, currency = 'INR'): string {
  if (val == null || isNaN(val)) return '—'
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
  if (val == null || isNaN(val)) return '—'
  return `${val.toFixed(decimals)}%`
}
