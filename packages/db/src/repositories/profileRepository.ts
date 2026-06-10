import type { Database } from "better-sqlite3";
import { randomUUID } from "node:crypto";
import {
  CertificationEntrySchema,
  EducationEntrySchema,
  ExperienceEntrySchema,
  ProfileSchema,
  ProjectEntrySchema,
  SkillGroupSchema,
  UploadedFileSchema
} from "@applyocalypse/shared-schemas";
import type { z } from "zod";
import { parseJsonColumn, stringifyJsonColumn } from "../json";

export type Profile = z.infer<typeof ProfileSchema>;
export type EducationEntry = z.infer<typeof EducationEntrySchema>;
export type ExperienceEntry = z.infer<typeof ExperienceEntrySchema>;
export type ProjectEntry = z.infer<typeof ProjectEntrySchema>;
export type CertificationEntry = z.infer<typeof CertificationEntrySchema>;
export type SkillGroup = z.infer<typeof SkillGroupSchema>;
export type CanonicalUploadedFile = z.infer<typeof UploadedFileSchema>;

export type CanonicalProfile = {
  profile: Profile;
  education: EducationEntry[];
  experience: ExperienceEntry[];
  projects: ProjectEntry[];
  certifications: CertificationEntry[];
  skillGroups: SkillGroup[];
  uploadedFiles: CanonicalUploadedFile[];
};

type ProfileRow = {
  id: string;
  display_name: string;
  legal_name: string;
  email: string | null;
  application_email: string | null;
  application_password_secret_ref_id: string | null;
  otp_provider_connection_id: string | null;
  otp_handling_enabled: number;
  phone: string | null;
  location: string | null;
  links_json: string;
  job_defaults_json: string;
  work_authorization_json: string;
  equal_employment_defaults_json: string;
  created_at: string;
  updated_at: string;
};

const mapProfileRow = (row: ProfileRow): Profile =>
  ProfileSchema.parse({
    id: row.id,
    displayName: row.display_name,
    legalName: row.legal_name,
    email: row.email,
    applicationEmail: row.application_email,
    applicationPasswordConfigured: Boolean(row.application_password_secret_ref_id),
    otpProviderConnectionId: row.otp_provider_connection_id,
    otpHandlingEnabled: row.otp_handling_enabled === 1,
    phone: row.phone,
    location: row.location,
    links: parseJsonColumn(row.links_json, []),
    jobDefaults: parseJsonColumn(row.job_defaults_json, {}),
    workAuthorization: parseJsonColumn(row.work_authorization_json, {}),
    equalEmploymentDefaults: parseJsonColumn(row.equal_employment_defaults_json, {}),
    createdAt: row.created_at,
    updatedAt: row.updated_at
  });

export class ProfileRepository {
  constructor(private readonly db: Database) {}

  getDefaultProfile(): Profile | null {
    const row = this.db
      .prepare("SELECT * FROM profiles WHERE deleted_at IS NULL ORDER BY created_at ASC LIMIT 1")
      .get() as ProfileRow | undefined;
    return row ? mapProfileRow(row) : null;
  }

  getById(profileId: string): Profile | null {
    const row = this.db
      .prepare("SELECT * FROM profiles WHERE id = ? AND deleted_at IS NULL")
      .get(profileId) as ProfileRow | undefined;
    return row ? mapProfileRow(row) : null;
  }

  createStarterProfile(input: { legalName: string; email?: string | null; location?: string | null }): Profile {
    const now = new Date().toISOString();
    const profile = ProfileSchema.parse({
      id: randomUUID(),
      displayName: input.legalName,
      legalName: input.legalName,
      email: input.email ?? null,
      applicationEmail: input.email ?? null,
      applicationPasswordConfigured: false,
      otpProviderConnectionId: null,
      otpHandlingEnabled: false,
      phone: null,
      location: input.location ?? null,
      links: [],
      jobDefaults: {},
      workAuthorization: {},
      equalEmploymentDefaults: {},
      createdAt: now,
      updatedAt: now
    });
    return this.upsert(profile);
  }

  upsert(profile: Profile): Profile {
    const parsed = ProfileSchema.parse(profile);
    const now = new Date().toISOString();
    const createdAt = parsed.createdAt || now;

    this.db
      .prepare(
        `
        INSERT INTO profiles (
          id, display_name, legal_name, email, phone, location, links_json,
          application_email, otp_provider_connection_id, otp_handling_enabled,
          job_defaults_json, work_authorization_json, equal_employment_defaults_json,
          created_at, updated_at
        )
        VALUES (
          @id, @displayName, @legalName, @email, @phone, @location, @linksJson,
          @applicationEmail, @otpProviderConnectionId, @otpHandlingEnabled,
          @jobDefaultsJson, @workAuthorizationJson, @equalEmploymentDefaultsJson,
          @createdAt, @updatedAt
        )
        ON CONFLICT(id) DO UPDATE SET
          display_name = excluded.display_name,
          legal_name = excluded.legal_name,
          email = excluded.email,
          application_email = excluded.application_email,
          otp_provider_connection_id = excluded.otp_provider_connection_id,
          otp_handling_enabled = excluded.otp_handling_enabled,
          phone = excluded.phone,
          location = excluded.location,
          links_json = excluded.links_json,
          job_defaults_json = excluded.job_defaults_json,
          work_authorization_json = excluded.work_authorization_json,
          equal_employment_defaults_json = excluded.equal_employment_defaults_json,
          updated_at = excluded.updated_at
      `
      )
      .run({
        id: parsed.id,
        displayName: parsed.displayName,
        legalName: parsed.legalName,
        email: parsed.email,
        applicationEmail: parsed.applicationEmail,
        otpProviderConnectionId: parsed.otpProviderConnectionId,
        otpHandlingEnabled: parsed.otpHandlingEnabled ? 1 : 0,
        phone: parsed.phone,
        location: parsed.location,
        linksJson: stringifyJsonColumn(parsed.links),
        jobDefaultsJson: stringifyJsonColumn(parsed.jobDefaults),
        workAuthorizationJson: stringifyJsonColumn(parsed.workAuthorization),
        equalEmploymentDefaultsJson: stringifyJsonColumn(parsed.equalEmploymentDefaults),
        createdAt,
        updatedAt: now
      });

    return this.getById(parsed.id) ?? ProfileSchema.parse({ ...parsed, createdAt, updatedAt: now });
  }

  configureApplicationCredentials(input: {
    profileId: string;
    applicationEmail: string;
    passwordSecretRefId: string;
    otpProviderConnectionId?: string | null;
    otpHandlingEnabled?: boolean;
  }): Profile {
    const now = new Date().toISOString();
    this.db
      .prepare(
        `
        UPDATE profiles
        SET application_email = @applicationEmail,
            application_password_secret_ref_id = @passwordSecretRefId,
            otp_provider_connection_id = @otpProviderConnectionId,
            otp_handling_enabled = @otpHandlingEnabled,
            updated_at = @updatedAt
        WHERE id = @profileId
          AND deleted_at IS NULL
      `
      )
      .run({
        profileId: input.profileId,
        applicationEmail: input.applicationEmail,
        passwordSecretRefId: input.passwordSecretRefId,
        otpProviderConnectionId: input.otpProviderConnectionId ?? null,
        otpHandlingEnabled: input.otpHandlingEnabled ? 1 : 0,
        updatedAt: now
      });

    const profile = this.getById(input.profileId);
    if (!profile) {
      throw new Error(`Profile not found: ${input.profileId}`);
    }
    return profile;
  }

  replaceStructuredSections(
    profileId: string,
    payload: {
      education: Array<{ id?: string | null | undefined; institution: string; degree?: string | null | undefined; field?: string | null | undefined; startDate?: string | null | undefined; endDate?: string | null | undefined }>;
      experience: Array<{ id?: string | null | undefined; company: string; title: string; location?: string | null | undefined; startDate?: string | null | undefined; endDate?: string | null | undefined; bullets?: string[] }>;
      projects: Array<{ id?: string | null | undefined; name: string; summary?: string | null | undefined; bullets?: string[]; tools?: string[] }>;
      skillGroups: Array<{ id?: string | null | undefined; label: string; skills?: string[] }>;
    }
  ): CanonicalProfile | null {
    const now = new Date().toISOString();
    this.db.transaction(() => {
      this.db.prepare("UPDATE education_entries SET deleted_at = ? WHERE profile_id = ? AND deleted_at IS NULL").run(now, profileId);
      this.db.prepare("UPDATE experience_entries SET deleted_at = ? WHERE profile_id = ? AND deleted_at IS NULL").run(now, profileId);
      this.db.prepare("UPDATE project_entries SET deleted_at = ? WHERE profile_id = ? AND deleted_at IS NULL").run(now, profileId);
      this.db.prepare("UPDATE skill_groups SET deleted_at = ? WHERE profile_id = ? AND deleted_at IS NULL").run(now, profileId);

      const insEdu = this.db.prepare("INSERT INTO education_entries (id, profile_id, institution, degree, field, start_date, end_date, details_json, source_confidence, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, '[]', 1.0, ?, ?)");
      for (const e of payload.education) {
        insEdu.run(e.id ?? randomUUID(), profileId, e.institution, e.degree ?? null, e.field ?? null, e.startDate ?? null, e.endDate ?? null, now, now);
      }

      const insExp = this.db.prepare("INSERT INTO experience_entries (id, profile_id, company, title, location, start_date, end_date, bullets_json, tools_json, source_confidence, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '[]', 1.0, ?, ?)");
      for (const e of payload.experience) {
        insExp.run(e.id ?? randomUUID(), profileId, e.company, e.title, e.location ?? null, e.startDate ?? null, e.endDate ?? null, JSON.stringify(e.bullets ?? []), now, now);
      }

      const insProj = this.db.prepare("INSERT INTO project_entries (id, profile_id, name, role, summary, bullets_json, tools_json, links_json, source_confidence, created_at, updated_at) VALUES (?, ?, ?, NULL, ?, ?, ?, '[]', 1.0, ?, ?)");
      for (const p of payload.projects) {
        insProj.run(p.id ?? randomUUID(), profileId, p.name, p.summary ?? null, JSON.stringify(p.bullets ?? []), JSON.stringify(p.tools ?? []), now, now);
      }

      const insSkill = this.db.prepare("INSERT INTO skill_groups (id, profile_id, label, skills_json, source_confidence, created_at, updated_at) VALUES (?, ?, ?, ?, 1.0, ?, ?)");
      for (const g of payload.skillGroups) {
        insSkill.run(g.id ?? randomUUID(), profileId, g.label, JSON.stringify(g.skills ?? []), now, now);
      }
    })();
    return this.getCanonicalProfile(profileId);
  }

  getApplicationCredentialReference(profileId: string):
    | {
        applicationEmail: string | null;
        passwordSecretRefId: string | null;
        encryptedReference: string | null;
        otpHandlingEnabled: boolean;
        otpProviderConnectionId: string | null;
      }
    | null {
    const row = this.db
      .prepare(
        `
        SELECT
          profiles.application_email AS application_email,
          profiles.application_password_secret_ref_id AS password_secret_ref_id,
          profiles.otp_handling_enabled AS otp_handling_enabled,
          profiles.otp_provider_connection_id AS otp_provider_connection_id,
          encrypted_secrets.reference AS encrypted_reference
        FROM profiles
        LEFT JOIN encrypted_secrets
          ON encrypted_secrets.id = profiles.application_password_secret_ref_id
         AND encrypted_secrets.deleted_at IS NULL
        WHERE profiles.id = @profileId
          AND profiles.deleted_at IS NULL
        LIMIT 1
      `
      )
      .get({ profileId }) as
      | {
          application_email: string | null;
          password_secret_ref_id: string | null;
          encrypted_reference: string | null;
          otp_handling_enabled: number;
          otp_provider_connection_id: string | null;
        }
      | undefined;

    return row
      ? {
          applicationEmail: row.application_email,
          passwordSecretRefId: row.password_secret_ref_id,
          encryptedReference: row.encrypted_reference,
          otpHandlingEnabled: row.otp_handling_enabled === 1,
          otpProviderConnectionId: row.otp_provider_connection_id
        }
      : null;
  }

  getCanonicalProfile(profileId: string): CanonicalProfile | null {
    const profile = this.getById(profileId);
    if (!profile) {
      return null;
    }

    const education = (this.db.prepare("SELECT * FROM education_entries WHERE profile_id = ? AND deleted_at IS NULL ORDER BY start_date").all(profileId) as Array<{
      id: string;
      profile_id: string;
      institution: string;
      degree: string | null;
      field: string | null;
      start_date: string | null;
      end_date: string | null;
      details_json: string;
      source_confidence: number;
    }>).map((row) =>
      EducationEntrySchema.parse({
        id: row.id,
        profileId: row.profile_id,
        institution: row.institution,
        degree: row.degree,
        field: row.field,
        startDate: row.start_date,
        endDate: row.end_date,
        details: parseJsonColumn(row.details_json, []),
        confidence: row.source_confidence
      })
    );

    const experience = (this.db.prepare("SELECT * FROM experience_entries WHERE profile_id = ? AND deleted_at IS NULL ORDER BY start_date DESC").all(profileId) as Array<{
      id: string;
      profile_id: string;
      company: string;
      title: string;
      location: string | null;
      start_date: string | null;
      end_date: string | null;
      bullets_json: string;
      tools_json: string;
      source_confidence: number;
    }>).map((row) =>
      ExperienceEntrySchema.parse({
        id: row.id,
        profileId: row.profile_id,
        company: row.company,
        title: row.title,
        location: row.location,
        startDate: row.start_date,
        endDate: row.end_date,
        bullets: parseJsonColumn(row.bullets_json, []),
        tools: parseJsonColumn(row.tools_json, []),
        confidence: row.source_confidence
      })
    );

    const projects = (this.db.prepare("SELECT * FROM project_entries WHERE profile_id = ? AND deleted_at IS NULL ORDER BY created_at").all(profileId) as Array<{
      id: string;
      profile_id: string;
      name: string;
      role: string | null;
      summary: string | null;
      bullets_json: string;
      tools_json: string;
      links_json: string;
      source_confidence: number;
    }>).map((row) =>
      ProjectEntrySchema.parse({
        id: row.id,
        profileId: row.profile_id,
        name: row.name,
        role: row.role,
        summary: row.summary,
        bullets: parseJsonColumn(row.bullets_json, []),
        tools: parseJsonColumn(row.tools_json, []),
        links: parseJsonColumn(row.links_json, []),
        confidence: row.source_confidence
      })
    );

    const certifications = (this.db.prepare("SELECT * FROM certification_entries WHERE profile_id = ? AND deleted_at IS NULL ORDER BY issued_at DESC, created_at DESC").all(profileId) as Array<{
      id: string;
      profile_id: string;
      name: string;
      issuer: string | null;
      issued_at: string | null;
      expires_at: string | null;
      credential_url: string | null;
      source_confidence: number;
    }>).map((row) =>
      CertificationEntrySchema.parse({
        id: row.id,
        profileId: row.profile_id,
        name: row.name,
        issuer: row.issuer,
        issuedAt: row.issued_at,
        expiresAt: row.expires_at,
        credentialUrl: row.credential_url,
        confidence: row.source_confidence
      })
    );

    const skillGroups = (this.db.prepare("SELECT * FROM skill_groups WHERE profile_id = ? AND deleted_at IS NULL ORDER BY created_at").all(profileId) as Array<{
      id: string;
      profile_id: string;
      label: string;
      skills_json: string;
      source_confidence: number;
    }>).map((row) =>
      SkillGroupSchema.parse({
        id: row.id,
        profileId: row.profile_id,
        label: row.label,
        skills: parseJsonColumn(row.skills_json, []),
        confidence: row.source_confidence
      })
    );

    const uploadedFiles = (this.db.prepare("SELECT * FROM uploaded_files WHERE profile_id = ? AND deleted_at IS NULL ORDER BY created_at DESC").all(profileId) as Array<{
      id: string;
      profile_id: string | null;
      file_kind: string;
      source_format: string;
      original_name: string;
      local_path: string;
      mime_type: string | null;
      size_bytes: number;
      sha256: string | null;
      status: string;
      created_at: string;
      updated_at: string;
    }>).map((row) =>
      UploadedFileSchema.parse({
        id: row.id,
        profileId: row.profile_id,
        fileKind: row.file_kind,
        sourceFormat: row.source_format,
        originalName: row.original_name,
        localPath: row.local_path,
        mimeType: row.mime_type,
        sizeBytes: row.size_bytes,
        sha256: row.sha256,
        status: row.status,
        createdAt: row.created_at,
        updatedAt: row.updated_at
      })
    );

    return { profile, education, experience, projects, certifications, skillGroups, uploadedFiles };
  }
}
