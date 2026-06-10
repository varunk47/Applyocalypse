/** Format an ISO date string (YYYY-MM-DD or ISO datetime) as MM/DD/YYYY for display/collection. */
export const formatDateMMDDYYYY = (isoDate: string | null | undefined): string | null => {
  if (!isoDate) return null;
  const match = isoDate.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!match) return null;
  const [, year, month, day] = match;
  return `${month}/${day}/${year}`;
};

/** Parse a MM/DD/YYYY string into an ISO date string (YYYY-MM-DD). Returns null for invalid input. */
export const parseDateMMDDYYYY = (mmddyyyy: string | null | undefined): string | null => {
  if (!mmddyyyy) return null;
  const match = mmddyyyy.trim().match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (!match) return null;
  const [, month, day, year] = match;
  if (!month || !day || !year) return null;
  const m = month.padStart(2, "0");
  const d = day.padStart(2, "0");
  return `${year}-${m}-${d}`;
};

/** Derive firstName from legalName (first space-delimited token). */
export const deriveFirstName = (legalName: string): string => legalName.split(" ")[0] ?? legalName;

/** Derive lastName from legalName (everything after the first token). */
export const deriveLastName = (legalName: string): string => {
  const parts = legalName.split(" ");
  return parts.length > 1 ? parts.slice(1).join(" ") : "";
};
