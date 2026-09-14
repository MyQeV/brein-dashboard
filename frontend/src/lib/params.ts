/** Search-param helpers. Use these before any list page needs them. */

/** The *resolved* value: in Next 16 a page receives `Promise<SearchParams>`,
 *  so call sites must `await searchParams` before using these helpers. */
export type SearchParams = Record<string, string | string[] | undefined>;

/**
 * Next delivers a repeated query key (`?q=a&q=b`) as a string[] at runtime,
 * so every read has to collapse it or the value is silently an array.
 */
export function firstParam(value: string | string[] | undefined): string | undefined {
  if (Array.isArray(value)) return value[0];
  return value;
}

export const PAGE_SIZES = [10, 25, 50, 100] as const;
export const DEFAULT_PAGE_SIZE = 25;

/**
 * Clamp an untrusted page number to a positive integer.
 *
 * A bare `Number(searchParams.page)` yields NaN for "abc", which reaches the
 * API as `page=NaN`, returns 422 and blanks the whole route in an error
 * boundary — for what is only ever a malformed URL.
 */
export function clampPage(value: string | string[] | undefined): number {
  const parsed = Number.parseInt(firstParam(value) ?? "", 10);
  if (!Number.isFinite(parsed) || parsed < 1) return 1;
  return parsed;
}

export function clampPageSize(
  value: string | string[] | undefined,
  fallback: number = DEFAULT_PAGE_SIZE,
): number {
  const parsed = Number.parseInt(firstParam(value) ?? "", 10);
  if (!Number.isFinite(parsed)) return fallback;
  return (PAGE_SIZES as readonly number[]).includes(parsed) ? parsed : fallback;
}

/** Build a query string, dropping empty values so URLs stay readable. */
export function buildQuery(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "") continue;
    search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `?${query}` : "";
}
