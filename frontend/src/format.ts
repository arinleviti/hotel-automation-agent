/**
 * Small text helpers used by several components. Plain functions, no React.
 */

/**
 * The display name of an address. Examples:
 *   "Sarah Mitchell <sarah.mitchell@mail.example>"  -> "Sarah Mitchell"
 *   "billing@frontrangeprovisions.example"          -> "billing@frontrangeprovisions.example"
 */
export function displayName(address: string): string {
  const name = address.split("<")[0].trim().replace(/^"|"$/g, "");   // text before "<", without quotes
  return name || address;
}

/**
 * A short date for the inbox. Example: "2026-11-02T18:41:00-07:00" -> "Nov 2".
 * timeZone "America/Denver": the hotel's time, so every visitor sees the same date as the email.
 */
export function shortDate(iso: string | null): string {
  if (iso === null) return "";
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "America/Denver" });
}

/** A full date for the email view. Example: "Mon, Nov 2, 2026, 6:41 PM". */
export function longDate(iso: string | null): string {
  if (iso === null) return "";
  return new Date(iso).toLocaleString("en-US", {
    weekday: "short", month: "short", day: "numeric", year: "numeric",
    hour: "numeric", minute: "2-digit", timeZone: "America/Denver",
  });
}

/** A file size. Example: 41873 -> "41 KB". */
export function fileSize(bytes: number): string {
  return bytes < 1024 ? `${bytes} B` : `${Math.round(bytes / 1024)} KB`;
}
