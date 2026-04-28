import type { Database } from "better-sqlite3";
import { randomUUID } from "node:crypto";
import {
  ParsedDocumentCanonicalSchema,
  ParsedDocumentMergeSummarySchema,
  ParsedDocumentSchema,
  ProfileSchema
} from "@applyocalypse/shared-schemas";
import type { z } from "zod";
import { parseJsonColumn, stringifyJsonColumn } from "../json";
import { ProfileRepository } from "./profileRepository";

export type ParsedDocument = z.infer<typeof ParsedDocumentSchema>;
export type ParsedDocumentCanonical = z.infer<typeof ParsedDocumentCanonicalSchema>;
export type ParsedDocumentMergeSummary = z.infer<typeof ParsedDocumentMergeSummarySchema>;
export type ParsedDocumentInput = {
  uploadedFileId: string;
  parserName: string;
  parserVersion: string;
  confidence: number;
  canonical: ParsedDocumentCanonical;
  styleMap?: Record<string, unknown>;
  anchorMap?: Record<string, unknown>;
  warnings?: string[];
};

type UploadedFileRow = {
  id: string;
  profile_id: string | null;
  file_kind: string;
};

type ParsedDocumentRow = {
  id: string;
  uploaded_file_id: string;
  parser_name: string;
  parser_version: string;
  confidence: number;
  canonical_json: string;
  style_map_json: string;
  anchor_map_json: string;
  warnings_json: string;
  created_at: string;
  updated_at: string;
};

const normalizeKey = (value: string): string => value.trim().toLowerCase().replace(/\s+/g, " ");

const normalizedSkillSet = (skills: string[]): Set<string> => new Set(skills.map(normalizeKey).filter(Boolean));

const hasMeaningfulSkillOverlap = (existing: string[], incoming: string[]): boolean => {
  const existingSet = normalizedSkillSet(existing);
  if (existingSet.size === 0) {
    return false;
  }
  return incoming.map(normalizeKey).some((skill) => existingSet.has(skill));
};

const sameText = (left: string | null | undefined, right: string | null | undefined): boolean =>
  normalizeKey(left ?? "") === normalizeKey(right ?? "");

const highConfidence = (confidence: number): boolean => confidence >= 0.75;

const mapParsedDocumentRow = (row: ParsedDocumentRow): ParsedDocument =>
  ParsedDocumentSchema.parse({
    id: row.id,
    uploadedFileId: row.uploaded_file_id,
    parserName: row.parser_name,
    parserVersion: row.parser_version,
    confidence: row.confidence,
    canonical: parseJsonColumn(row.canonical_json, {}),
    styleMap: parseJsonColumn(row.style_map_json, {}),
    anchorMap: parseJsonColumn(row.anchor_map_json, {}),
    warnings: parseJsonColumn(row.warnings_json, []),
    createdAt: row.created_at,
    updatedAt: row.updated_at
  });

export class ParsedDocumentRepository {
  constructor(private readonly db: Database) {}

  list(input: { uploadedFileId?: string; profileId?: string | null } = {}): ParsedDocument[] {
    const rows = input.uploadedFileId
      ? (this.db
          .prepare("SELECT * FROM parsed_documents WHERE uploaded_file_id = ? ORDER BY created_at DESC")
          .all(input.uploadedFileId) as ParsedDocumentRow[])
      : input.profileId
        ? (this.db
            .prepare(
              `
              SELECT parsed_documents.*
              FROM parsed_documents
              INNER JOIN uploaded_files ON uploaded_files.id = parsed_documents.uploaded_file_id
              WHERE uploaded_files.profile_id = ? AND uploaded_files.deleted_at IS NULL
              ORDER BY parsed_documents.created_at DESC
            `
            )
            .all(input.profileId) as ParsedDocumentRow[])
        : (this.db.prepare("SELECT * FROM parsed_documents ORDER BY created_at DESC").all() as ParsedDocumentRow[]);
    return rows.map(mapParsedDocumentRow);
  }

  getById(id: string): ParsedDocument {
    const row = this.db.prepare("SELECT * FROM parsed_documents WHERE id = ?").get(id) as ParsedDocumentRow | undefined;
    if (!row) {
      throw new Error(`Parsed document not found: ${id}`);
    }
    return mapParsedDocumentRow(row);
  }

  create(input: ParsedDocumentInput): ParsedDocument {
    const now = new Date().toISOString();
    const parsed = ParsedDocumentSchema.parse({
      id: randomUUID(),
      uploadedFileId: input.uploadedFileId,
      parserName: input.parserName,
      parserVersion: input.parserVersion,
      confidence: input.confidence,
      canonical: input.canonical,
      styleMap: input.styleMap ?? {},
      anchorMap: input.anchorMap ?? {},
      warnings: input.warnings ?? [],
      createdAt: now,
      updatedAt: now
    });

    this.db
      .prepare(
        `
        INSERT INTO parsed_documents (
          id, uploaded_file_id, parser_name, parser_version, confidence,
          canonical_json, style_map_json, anchor_map_json, warnings_json, created_at, updated_at
        )
        VALUES (
          @id, @uploadedFileId, @parserName, @parserVersion, @confidence,
          @canonicalJson, @styleMapJson, @anchorMapJson, @warningsJson, @createdAt, @updatedAt
        )
      `
      )
      .run({
        id: parsed.id,
        uploadedFileId: parsed.uploadedFileId,
        parserName: parsed.parserName,
        parserVersion: parsed.parserVersion,
        confidence: parsed.confidence,
        canonicalJson: stringifyJsonColumn(parsed.canonical),
        styleMapJson: stringifyJsonColumn(parsed.styleMap),
        anchorMapJson: stringifyJsonColumn(parsed.anchorMap),
        warningsJson: JSON.stringify(parsed.warnings),
        createdAt: parsed.createdAt,
        updatedAt: parsed.updatedAt
      });

    return parsed;
  }

  createAndMerge(input: ParsedDocumentInput): ParsedDocumentMergeSummary {
    const transaction = this.db.transaction((innerInput: ParsedDocumentInput) => {
      const parsedDocument = this.create(innerInput);
      return this.mergeIntoProfile(parsedDocument);
    });
    return transaction(input) as ParsedDocumentMergeSummary;
  }

  mergeIntoProfile(parsedDocument: ParsedDocument): ParsedDocumentMergeSummary {
    const uploadedFile = this.db
      .prepare("SELECT id, profile_id, file_kind FROM uploaded_files WHERE id = ? AND deleted_at IS NULL")
      .get(parsedDocument.uploadedFileId) as UploadedFileRow | undefined;
    if (!uploadedFile?.profile_id) {
      return ParsedDocumentMergeSummarySchema.parse({
        parsedDocument,
        updatedProfile: null,
        applied: [],
        skipped: ["No profile is attached to the uploaded file."],
        requiresReview: true
      });
    }

    const profileRepository = new ProfileRepository(this.db);
    const existing = profileRepository.getCanonicalProfile(uploadedFile.profile_id);
    if (!existing) {
      return ParsedDocumentMergeSummarySchema.parse({
        parsedDocument,
        updatedProfile: null,
        applied: [],
        skipped: ["Attached profile no longer exists."],
        requiresReview: true
      });
    }

    const applied: string[] = [];
    const skipped: string[] = [];
    const now = new Date().toISOString();
    const snapshotId = randomUUID();
    this.db
      .prepare(
        `
        INSERT INTO profile_snapshots (id, profile_id, reason, snapshot_json, created_at)
        VALUES (@id, @profileId, @reason, @snapshotJson, @createdAt)
      `
      )
      .run({
        id: snapshotId,
        profileId: existing.profile.id,
        reason: "parsed_document_merge",
        snapshotJson: stringifyJsonColumn(existing),
        createdAt: now
      });

    const identity = parsedDocument.canonical.identity;
    const nextProfile = ProfileSchema.parse({
      ...existing.profile,
      email: existing.profile.email ?? identity.email ?? null,
      phone: existing.profile.phone ?? identity.phone ?? null,
      location: existing.profile.location ?? identity.location ?? null,
      links: existing.profile.links.length > 0 ? existing.profile.links : identity.links,
      updatedAt: now
    });

    if (!existing.profile.email && identity.email) applied.push("profile.email");
    if (!existing.profile.phone && identity.phone) applied.push("profile.phone");
    if (!existing.profile.location && identity.location) applied.push("profile.location");
    if (existing.profile.links.length === 0 && identity.links.length > 0) applied.push("profile.links");

    profileRepository.upsert(nextProfile);

    for (const education of parsedDocument.canonical.education) {
      if (!highConfidence(education.confidence)) {
        skipped.push(`education:${education.institution}:low_confidence`);
        continue;
      }
      const duplicate = existing.education.some(
        (entry) =>
          sameText(entry.institution, education.institution) &&
          (sameText(entry.degree, education.degree) || sameText(entry.field, education.field))
      );
      if (duplicate) {
        skipped.push(`education:${education.institution}:duplicate`);
        continue;
      }
      this.db
        .prepare(
          `
          INSERT INTO education_entries (
            id, profile_id, institution, degree, field, start_date, end_date,
            details_json, source_confidence, created_at, updated_at
          )
          VALUES (
            @id, @profileId, @institution, @degree, @field, @startDate, @endDate,
            @detailsJson, @confidence, @createdAt, @updatedAt
          )
        `
        )
        .run({
          id: randomUUID(),
          profileId: existing.profile.id,
          institution: education.institution,
          degree: education.degree,
          field: education.field,
          startDate: education.startDate,
          endDate: education.endDate,
          detailsJson: JSON.stringify(education.details),
          confidence: education.confidence,
          createdAt: now,
          updatedAt: now
        });
      applied.push(`education:${education.institution}`);
    }

    for (const experience of parsedDocument.canonical.experience) {
      if (!highConfidence(experience.confidence)) {
        skipped.push(`experience:${experience.company}:${experience.title}:low_confidence`);
        continue;
      }
      const duplicate = existing.experience.some(
        (entry) => sameText(entry.company, experience.company) && sameText(entry.title, experience.title)
      );
      if (duplicate) {
        skipped.push(`experience:${experience.company}:${experience.title}:duplicate`);
        continue;
      }
      this.db
        .prepare(
          `
          INSERT INTO experience_entries (
            id, profile_id, company, title, location, start_date, end_date,
            bullets_json, tools_json, source_confidence, created_at, updated_at
          )
          VALUES (
            @id, @profileId, @company, @title, @location, @startDate, @endDate,
            @bulletsJson, @toolsJson, @confidence, @createdAt, @updatedAt
          )
        `
        )
        .run({
          id: randomUUID(),
          profileId: existing.profile.id,
          company: experience.company,
          title: experience.title,
          location: experience.location,
          startDate: experience.startDate,
          endDate: experience.endDate,
          bulletsJson: JSON.stringify(experience.bullets),
          toolsJson: JSON.stringify(experience.tools),
          confidence: experience.confidence,
          createdAt: now,
          updatedAt: now
        });
      applied.push(`experience:${experience.company}:${experience.title}`);
    }

    for (const project of parsedDocument.canonical.projects) {
      if (!highConfidence(project.confidence)) {
        skipped.push(`project:${project.name}:low_confidence`);
        continue;
      }
      const duplicate = existing.projects.some((entry) => sameText(entry.name, project.name));
      if (duplicate) {
        skipped.push(`project:${project.name}:duplicate`);
        continue;
      }
      this.db
        .prepare(
          `
          INSERT INTO project_entries (
            id, profile_id, name, role, summary, bullets_json, tools_json,
            links_json, source_confidence, created_at, updated_at
          )
          VALUES (
            @id, @profileId, @name, @role, @summary, @bulletsJson, @toolsJson,
            @linksJson, @confidence, @createdAt, @updatedAt
          )
        `
        )
        .run({
          id: randomUUID(),
          profileId: existing.profile.id,
          name: project.name,
          role: project.role,
          summary: project.summary,
          bulletsJson: JSON.stringify(project.bullets),
          toolsJson: JSON.stringify(project.tools),
          linksJson: JSON.stringify(project.links),
          confidence: project.confidence,
          createdAt: now,
          updatedAt: now
        });
      applied.push(`project:${project.name}`);
    }

    for (const certification of parsedDocument.canonical.certifications) {
      if (!highConfidence(certification.confidence)) {
        skipped.push(`certification:${certification.name}:low_confidence`);
        continue;
      }
      const duplicate = existing.certifications.some(
        (entry) => sameText(entry.name, certification.name) && sameText(entry.issuer, certification.issuer)
      );
      if (duplicate) {
        skipped.push(`certification:${certification.name}:duplicate`);
        continue;
      }
      this.db
        .prepare(
          `
          INSERT INTO certification_entries (
            id, profile_id, name, issuer, issued_at, expires_at, credential_url,
            source_confidence, created_at, updated_at
          )
          VALUES (
            @id, @profileId, @name, @issuer, @issuedAt, @expiresAt, @credentialUrl,
            @confidence, @createdAt, @updatedAt
          )
        `
        )
        .run({
          id: randomUUID(),
          profileId: existing.profile.id,
          name: certification.name,
          issuer: certification.issuer,
          issuedAt: certification.issuedAt,
          expiresAt: certification.expiresAt,
          credentialUrl: certification.credentialUrl,
          confidence: certification.confidence,
          createdAt: now,
          updatedAt: now
        });
      applied.push(`certification:${certification.name}`);
    }

    for (const skillGroup of parsedDocument.canonical.skillGroups) {
      if (skillGroup.confidence < 0.7 || skillGroup.skills.length === 0) {
        skipped.push(`skill_group:${skillGroup.label}:low_confidence`);
        continue;
      }
      const duplicate = existing.skillGroups.some(
        (existingGroup) =>
          normalizeKey(existingGroup.label) === normalizeKey(skillGroup.label) ||
          hasMeaningfulSkillOverlap(existingGroup.skills, skillGroup.skills)
      );
      if (duplicate) {
        skipped.push(`skill_group:${skillGroup.label}:duplicate`);
        continue;
      }
      this.db
        .prepare(
          `
          INSERT INTO skill_groups (
            id, profile_id, label, skills_json, source_confidence, created_at, updated_at
          )
          VALUES (@id, @profileId, @label, @skillsJson, @confidence, @createdAt, @updatedAt)
        `
        )
        .run({
          id: randomUUID(),
          profileId: existing.profile.id,
          label: skillGroup.label,
          skillsJson: JSON.stringify(skillGroup.skills),
          confidence: skillGroup.confidence,
          createdAt: now,
          updatedAt: now
        });
      applied.push(`skill_group:${skillGroup.label}`);
    }

    const updatedProfile = profileRepository.getById(existing.profile.id);
    return ParsedDocumentMergeSummarySchema.parse({
      parsedDocument,
      updatedProfile,
      applied,
      skipped,
      requiresReview: parsedDocument.confidence < 0.75 || parsedDocument.warnings.length > 0 || skipped.some((item) => item.includes("low_confidence"))
    });
  }
}
