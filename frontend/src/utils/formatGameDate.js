export function formatGameDate(dateString) {
  // dateString looks like "2026-04-15"
  const [year, month, day] = dateString.split("-").map(Number);
  const date = new Date(year, month - 1, day);   // month - 1: JS months are 0-indexed
  return date.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",   // "Apr"
    day: "numeric",
  });
}