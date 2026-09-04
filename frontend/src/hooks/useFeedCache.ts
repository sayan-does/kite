export const CACHE_KEY_ALL = '__all__'
export const PREFETCH_TTL_MS = 5 * 60 * 1000

export function cacheKey(tag: string) {
  return tag || CACHE_KEY_ALL
}

export function isCacheStale(fetchedAt: number, now = Date.now()) {
  return now - fetchedAt > PREFETCH_TTL_MS
}
