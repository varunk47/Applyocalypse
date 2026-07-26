import type { ProfileRepository } from "@applyocalypse/db";

type ProfileLookup = Pick<ProfileRepository, "getById" | "getDefaultProfile">;

/**
 * Decide which profile an upload belongs to.
 *
 * The renderer sends whatever profile its store happens to hold, which is null
 * before the store hydrates and stale after a profile is replaced. An upload
 * that lands without a profile can never be merged, so main resolves ownership
 * itself instead of trusting the renderer.
 */
export const resolveOwningProfileId = (requestedProfileId: string | null, profiles: ProfileLookup): string | null => {
  if (requestedProfileId && profiles.getById(requestedProfileId)) {
    return requestedProfileId;
  }
  return profiles.getDefaultProfile()?.id ?? null;
};
