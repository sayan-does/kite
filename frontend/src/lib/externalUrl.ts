/** Ensure outbound links are absolute https URLs. */
export function normalizeExternalUrl(raw: string | null | undefined): string | null {
  const value = (raw || '').trim()
  if (!value) return null

  if (/^https?:\/\//i.test(value)) return value
  if (value.startsWith('//')) return `https:${value}`

  // Scheme-less host paths from canonicalization (e.g. example.com/path)
  if (/^[\w.-]+\.[a-z]{2,}/i.test(value)) {
    return `https://${value.replace(/^\/+/, '')}`
  }

  try {
    const parsed = new URL(value, window.location.origin)
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      return parsed.href
    }
  } catch {
    return null
  }

  return null
}

export function openExternalUrl(url: string | null | undefined): boolean {
  const normalized = normalizeExternalUrl(url)
  if (!normalized) return false
  window.open(normalized, '_blank', 'noopener,noreferrer')
  return true
}
