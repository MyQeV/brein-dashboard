/**
 * Reading API metric rows.
 *
 * The dashboard endpoints merge rows from three media servers, and the key
 * names are not uniform: a label arrives as `label` or `display_label` or
 * `display_name` depending on which store built the row, and watch time as
 * `total_seconds`, `seconds` or `watch_time_seconds`. Every view therefore
 * reads defensively, and until now each one carried its own copy of the same
 * two loops — which is how a card once ended up keyed on `label` while the
 * rows it was given only had `display_label`, collapsing the whole list into
 * one untitled entry.
 *
 * One place to change when the API's names settle.
 */

/** A metric row as it arrives: an object whose keys vary by source. */
export type ApiRow = Record<string, unknown>;

/** Watch-time value keys, most canonical first. */
const SECONDS_KEYS = ["total_seconds", "seconds", "watch_time_seconds"];

/** Human-readable name keys, most canonical first. */
const LABEL_KEYS = ["label", "display_label", "display_name", "name"];

/**
 * First key holding a number, else 0. A missing metric is an absent row, not
 * a reason to render NaN.
 */
export function rowNumber(row: ApiRow, keys: string[] = SECONDS_KEYS): number {
  for (const key of keys) {
    const value = row[key];
    if (typeof value === "number") return value;
  }
  return 0;
}

/**
 * First key holding a non-empty string (or any number, stringified), else
 * `fallback`. Numbers count because ids arrive both ways.
 */
export function rowText(row: ApiRow, keys: string[] = LABEL_KEYS, fallback = ""): string {
  for (const key of keys) {
    const value = row[key];
    if (typeof value === "string" && value) return value;
    if (typeof value === "number") return String(value);
  }
  return fallback;
}
