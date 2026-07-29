import { IpcContracts } from "@applyocalypse/ipc-contracts";
import { handleContract, type IpcHandlerContext } from "./context";

export const registerProfileHandlers = (ctx: IpcHandlerContext): void => {
  const { profileRepository, providerRepository, auditRepository, secureSecretStore, uploadRepository, parsedDocumentRepository } =
    ctx;

  const configureApplicationCredentials = (input: {
    profileId: string;
    applicationEmail: string;
    applicationPassword: string;
    gmailOtpEnabled: boolean;
  }) => {
    const applicationEmail = input.applicationEmail.trim().toLowerCase();
    if (!profileRepository.getById(input.profileId)) {
      throw new Error("Profile was not found for application credential setup");
    }
    const encryptedReference = secureSecretStore.encryptSecret(input.applicationPassword);
    const secretRefId = providerRepository.createEncryptedSecretReference({
      provider: input.gmailOtpEnabled ? "gmail" : "local",
      keyName: input.gmailOtpEnabled ? "gmail_otp_password" : "application_password",
      encryptedReference,
      // Passwords are short; a prefix/suffix hint would persist most of the secret in plaintext.
      redactedHint: "[REDACTED]"
    });
    const gmailConnection = input.gmailOtpEnabled
      ? providerRepository.upsertConnection({
          provider: "gmail",
          displayName: `Gmail OTP (${applicationEmail})`,
          status: "CONNECTED",
          secretRefId,
          metadata: {
            email: applicationEmail,
            purpose: "otp",
            authMode: "password_or_app_password",
            scope: "gmail_imap_otp_search",
            configuredAt: new Date().toISOString()
          }
        })
      : null;
    if (!input.gmailOtpEnabled) {
      providerRepository.disconnectProvider("gmail", {
        email: applicationEmail,
        purpose: "otp",
        disabledAt: new Date().toISOString()
      });
    }
    const profile = profileRepository.configureApplicationCredentials({
      profileId: input.profileId,
      applicationEmail,
      passwordSecretRefId: secretRefId,
      otpProviderConnectionId: gmailConnection?.id ?? null,
      otpHandlingEnabled: input.gmailOtpEnabled
    });
    auditRepository.append({
      action: "profile.application_credentials_saved",
      entityType: "profile",
      entityId: profile.id,
      metadata: {
        applicationEmail,
        gmailOtpEnabled: input.gmailOtpEnabled,
        passwordSecretRefId: secretRefId,
        gmailProviderConnectionId: gmailConnection?.id ?? null
      }
    });
    return profile;
  };

  handleContract(IpcContracts.profileGet, () => profileRepository.getDefaultProfile());
  handleContract(IpcContracts.profileGetCanonical, ({ profileId }) => {
    const resolvedProfileId = profileId ?? profileRepository.getDefaultProfile()?.id ?? null;
    return resolvedProfileId ? profileRepository.getCanonicalProfile(resolvedProfileId) : null;
  });
  handleContract(IpcContracts.profileCreateStarter, (input) => {
    let profile = profileRepository.createStarterProfile({
      legalName: input.legalName,
      email: input.email ?? null,
      location: input.location ?? null
    });
    if (input.workAuthorization) {
      profile = profileRepository.upsert({ ...profile, workAuthorization: input.workAuthorization });
    }
    // Onboarding takes the resume before it asks for anything else, so on a fresh
    // install those uploads exist with no owner yet. Claim them and merge their
    // parses now, otherwise the profile stays empty despite a resume being read.
    for (const adopted of uploadRepository.adoptOrphanedFiles(profile.id)) {
      for (const parsedDocument of parsedDocumentRepository.list({ uploadedFileId: adopted.id })) {
        parsedDocumentRepository.mergeIntoProfile(parsedDocument);
      }
      auditRepository.append({
        action: "profile.orphaned_upload_adopted",
        entityType: "uploaded_file",
        entityId: adopted.id,
        metadata: { profileId: profile.id, fileKind: adopted.fileKind }
      });
    }
    return configureApplicationCredentials({
      profileId: profile.id,
      applicationEmail: input.applicationEmail,
      applicationPassword: input.applicationPassword,
      gmailOtpEnabled: input.gmailOtpEnabled
    });
  });
  handleContract(IpcContracts.profileConfigureApplicationCredentials, (input) =>
    configureApplicationCredentials({
      profileId: input.profileId,
      applicationEmail: input.applicationEmail,
      applicationPassword: input.applicationPassword,
      gmailOtpEnabled: input.gmailOtpEnabled
    })
  );
  handleContract(IpcContracts.profileUpdate, ({ profile }) => profileRepository.upsert(profile));
  handleContract(IpcContracts.profileUpdateStructured, ({ profileId, education, experience, projects, skillGroups }) => {
    const result = profileRepository.replaceStructuredSections(profileId, { education, experience, projects, skillGroups });
    auditRepository.append({
      action: "profile.structured_sections_replaced",
      entityType: "profile",
      entityId: profileId,
      metadata: { educationCount: education.length, experienceCount: experience.length, projectCount: projects.length, skillGroupCount: skillGroups.length }
    });
    return result;
  });
};
