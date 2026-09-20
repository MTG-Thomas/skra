/**
 * Allow only http(s) external URLs. Upstream-provided strings such as
 * `SyncMetadata.source_url` are unconstrained, so non-web schemes
 * (e.g. `javascript:`) must never reach an `href`.
 */
export function isSafeExternalUrl(url: string | null | undefined): boolean {
  if (!url) {
    return false;
  }
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}
