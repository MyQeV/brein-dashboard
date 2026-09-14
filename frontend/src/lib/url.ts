/**
 * Links out to a configured address.
 *
 * An instance's external URL is typed in by an admin and stored as free text,
 * and the pages that link to a media server render it for everyone — so a
 * `javascript:` URL saved there would run in another viewer's session when
 * they clicked the badge. That is an admin escalating into other people's
 * sessions, which is worth closing even though an admin has other powers.
 *
 * The API rejects a non-http(s) scheme on the way in; this is the second
 * half, for the rows already stored and for anything that reaches the page by
 * another route.
 */
export function externalHref(value: string | null | undefined): string | undefined {
  const raw = (value ?? "").trim();
  if (!raw) return undefined;
  try {
    const parsed = new URL(raw);
    // An allowlist, not a `javascript:` denylist: `data:`, `vbscript:` and
    // whatever comes next are all excluded by saying what is permitted.
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return undefined;
    return parsed.toString();
  } catch {
    // Not an absolute URL. A relative one cannot carry a scheme, so it is
    // harmless, but nothing here means to link inside the app.
    return undefined;
  }
}
