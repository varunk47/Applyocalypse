/**
 * Work authorization, as the portals actually ask it.
 *
 * Nearly every US application form asks two separate yes/no questions:
 *
 *   1. "Are you legally authorized to work in the United States?"
 *   2. "Will you now or in the future require sponsorship for employment
 *      visa status?"
 *
 * They are not the same question and they are not opposites. Someone on F-1
 * OPT answers Yes to both: authorized today, sponsorship needed later. A free
 * text summary cannot answer either one, because both are radio buttons whose
 * only options are Yes and No. So the profile stores the two answers, and the
 * prose summary is derived from them rather than typed, which keeps what the
 * user writes and what the worker clicks from drifting apart.
 */

export type WorkAuthorizationStatus =
  | "US_CITIZEN"
  | "PERMANENT_RESIDENT"
  | "F1_OPT"
  | "F1_CPT"
  | "H1B"
  | "OTHER_AUTHORIZED"
  | "NOT_YET_AUTHORIZED";

/** The answer to "will you now or in the future require sponsorship". */
export type SponsorshipNeed = "NEVER" | "NOW" | "FUTURE";

export type WorkAuthorizationOption = {
  readonly id: WorkAuthorizationStatus;
  readonly label: string;
  readonly authorizedInUs: boolean;
  /** Null where the status alone does not settle it and the user must say. */
  readonly defaultSponsorshipNeed: SponsorshipNeed | null;
};

export const WORK_AUTHORIZATION_STATUSES: readonly WorkAuthorizationOption[] = [
  {
    id: "US_CITIZEN",
    label: "US citizen",
    authorizedInUs: true,
    defaultSponsorshipNeed: "NEVER"
  },
  {
    id: "PERMANENT_RESIDENT",
    label: "Permanent resident (Green Card)",
    authorizedInUs: true,
    defaultSponsorshipNeed: "NEVER"
  },
  {
    id: "F1_OPT",
    label: "F-1 student on OPT",
    authorizedInUs: true,
    // Authorized today, and the work permit runs out. Answering No here is the
    // single most common way an application becomes a misrepresentation.
    defaultSponsorshipNeed: "FUTURE"
  },
  {
    id: "F1_CPT",
    label: "F-1 student on CPT",
    authorizedInUs: true,
    defaultSponsorshipNeed: "FUTURE"
  },
  {
    id: "H1B",
    label: "H-1B",
    authorizedInUs: true,
    // A new employer has to file the transfer, which the form counts as
    // sponsorship now.
    defaultSponsorshipNeed: "NOW"
  },
  {
    id: "OTHER_AUTHORIZED",
    label: "Authorized another way (TN, L-1, EAD, and so on)",
    authorizedInUs: true,
    defaultSponsorshipNeed: null
  },
  {
    id: "NOT_YET_AUTHORIZED",
    label: "Not authorized to work in the US yet",
    authorizedInUs: false,
    defaultSponsorshipNeed: "NOW"
  }
];

export type WorkAuthorizationAnswer = {
  readonly status: WorkAuthorizationStatus;
  readonly authorizedInUs: boolean;
  readonly sponsorshipNeed: SponsorshipNeed;
  readonly summary: string;
};

const SPONSORSHIP_PROSE: Record<SponsorshipNeed, string> = {
  NEVER: "I do not require sponsorship now or in the future.",
  NOW: "I require employer sponsorship.",
  FUTURE: "I am authorized to work now and will require sponsorship in the future."
};

const isSponsorshipNeed = (value: unknown): value is SponsorshipNeed =>
  value === "NEVER" || value === "NOW" || value === "FUTURE";

const optionFor = (status: WorkAuthorizationStatus): WorkAuthorizationOption | undefined =>
  WORK_AUTHORIZATION_STATUSES.find((option) => option.id === status);

/**
 * Turn a status, plus the user's own answer where the status does not settle
 * it, into the two facts a portal asks for.
 *
 * Returns null when the pair cannot be stated honestly: an unknown status, or
 * one whose sponsorship answer only the user knows and who has not said.
 */
export const deriveWorkAuthorization = (
  status: WorkAuthorizationStatus,
  sponsorshipNeed: SponsorshipNeed | null
): WorkAuthorizationAnswer | null => {
  const option = optionFor(status);
  if (!option) return null;

  const resolved = sponsorshipNeed ?? option.defaultSponsorshipNeed;
  if (!resolved) return null;

  // Someone who cannot work here today needs sponsorship by definition, so an
  // override saying otherwise is a mistake we refuse to write down.
  const need = option.authorizedInUs ? resolved : resolved === "NEVER" ? "NOW" : resolved;

  return {
    status,
    authorizedInUs: option.authorizedInUs,
    sponsorshipNeed: need,
    summary: `${option.label}. ${SPONSORSHIP_PROSE[need]}`
  };
};

/** Read a stored answer back, rejecting the free-text blob older profiles held. */
export const readWorkAuthorization = (stored: Record<string, unknown>): WorkAuthorizationAnswer | null => {
  const status = stored["status"];
  if (typeof status !== "string") return null;
  if (!optionFor(status as WorkAuthorizationStatus)) return null;

  const sponsorshipNeed = stored["sponsorshipNeed"];
  if (!isSponsorshipNeed(sponsorshipNeed)) return null;
  if (typeof stored["authorizedInUs"] !== "boolean") return null;

  return deriveWorkAuthorization(status as WorkAuthorizationStatus, sponsorshipNeed);
};
