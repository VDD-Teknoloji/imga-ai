// Invitation-token extractor.
//
// Sprint 8.3.2 smoke test surfaced a UX foot-gun: an admin copies the
// full link (`https://app.imga.ai/invite/<TOKEN>`) from the create-
// invitation dialog and pastes it into a context that expects a bare
// token — including, in the production repro, the URL bar of an
// incognito window that already contained `https://app.imga.ai/invite/`,
// resulting in `https://app.imga.ai/invite/https://app.imga.ai/invite/<TOKEN>`.
// Next.js read `params.token` as the inner full URL; the preview hook
// re-encoded it; the backend got `https%3A%2F%2F...` as the token and
// 404'd because no DB row hashes to that.
//
// `extractInvitationToken` accepts either a full URL or a bare token
// and returns the bare token. Idempotent and safe to call multiple
// times. We keep it strict on what counts as "URL-shaped" — only the
// `/invite/<segment>` path matches; query strings or fragments are
// treated as terminators so `?ref=email` doesn't bleed into the token.

const INVITE_PATH_RE = /\/invite\/([^/?#]+)/;

/**
 * Pull the bare invitation token out of either a full URL or a
 * pre-cleaned token. Whitespace is trimmed in both branches.
 *
 * Examples:
 *   extractInvitationToken("PMkWdVb9...")
 *     → "PMkWdVb9..."
 *   extractInvitationToken("https://app.imga.ai/invite/PMkWdVb9...")
 *     → "PMkWdVb9..."
 *   extractInvitationToken("https://app.imga.ai/invite/PMkWdVb9...?utm=mail")
 *     → "PMkWdVb9..."
 *   extractInvitationToken("  abc123  ")
 *     → "abc123"
 */
export function extractInvitationToken(input: string): string {
  const trimmed = input.trim();
  const match = trimmed.match(INVITE_PATH_RE);
  // match[1] can only be undefined if our regex's capture group had no
  // hits — but the group is mandatory and the regex matched, so the
  // optional chain + `?? trimmed` is just to satisfy strict TS without
  // an `as` cast.
  return match?.[1] ?? trimmed;
}
