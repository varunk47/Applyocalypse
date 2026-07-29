import type { Database } from "better-sqlite3";
import { randomUUID } from "node:crypto";
import { LlmProviderTypeSchema, ProviderConnectionSchema, ProviderTypeSchema, SecretProviderTypeSchema } from "@applyocalypse/shared-schemas";
import type { z } from "zod";
import { parseJsonColumn, stringifyJsonColumn } from "../json";

// Derived from the canonical enum so a newly-supported provider can never be silently skipped.
const LLM_PROVIDER_SQL_LIST = LlmProviderTypeSchema.options.map((provider) => `'${provider}'`).join(",");

export type ProviderConnection = z.infer<typeof ProviderConnectionSchema>;
export type ProviderType = z.infer<typeof ProviderTypeSchema>;
export type LlmProviderType = z.infer<typeof LlmProviderTypeSchema>;
export type SecretProviderType = z.infer<typeof SecretProviderTypeSchema>;

export type ProviderSecretReference<Provider extends ProviderType = ProviderType> = {
  provider: Provider;
  connectionId: string;
  secretRefId: string;
  encryptedReference: string;
  metadata: Record<string, unknown>;
};

type ProviderConnectionRow = {
  id: string;
  provider: string;
  display_name: string;
  status: string;
  secret_ref_id: string | null;
  metadata_json: string;
  created_at: string;
  updated_at: string;
};

const mapProviderConnectionRow = (row: ProviderConnectionRow): ProviderConnection =>
  ProviderConnectionSchema.parse({
    id: row.id,
    provider: row.provider,
    displayName: row.display_name,
    status: row.status,
    secretRefId: row.secret_ref_id,
    metadata: parseJsonColumn(row.metadata_json, {}),
    createdAt: row.created_at,
    updatedAt: row.updated_at
  });

export class ProviderRepository {
  constructor(private readonly db: Database) {}

  list(): ProviderConnection[] {
    const rows = this.db
      .prepare("SELECT * FROM provider_connections WHERE deleted_at IS NULL ORDER BY provider ASC, created_at ASC")
      .all() as ProviderConnectionRow[];
    return rows.map(mapProviderConnectionRow);
  }

  getFirstConnectedSecretReference(): ProviderSecretReference<LlmProviderType> | null {
    const row = this.db
      .prepare(
        `
        SELECT
          provider_connections.id AS connection_id,
          provider_connections.provider AS provider,
          provider_connections.secret_ref_id AS secret_ref_id,
          provider_connections.metadata_json AS metadata_json,
          encrypted_secrets.reference AS encrypted_reference
        FROM provider_connections
        JOIN encrypted_secrets ON encrypted_secrets.id = provider_connections.secret_ref_id
        WHERE provider_connections.deleted_at IS NULL
          AND provider_connections.status = 'CONNECTED'
          AND provider_connections.provider IN (${LLM_PROVIDER_SQL_LIST})
          AND encrypted_secrets.deleted_at IS NULL
        ORDER BY provider_connections.updated_at DESC
        LIMIT 1
      `
      )
      .get() as
      | {
          connection_id: string;
          provider: string;
          secret_ref_id: string;
          encrypted_reference: string;
          metadata_json: string;
        }
      | undefined;

    if (!row) {
      return null;
    }

    return {
      provider: LlmProviderTypeSchema.parse(row.provider),
      connectionId: row.connection_id,
      secretRefId: row.secret_ref_id,
      encryptedReference: row.encrypted_reference,
      metadata: parseJsonColumn(row.metadata_json, {})
    };
  }

  getConnectedSecretReferenceById(connectionId: string): ProviderSecretReference | null {
    const row = this.db
      .prepare(
        `
        SELECT
          provider_connections.id AS connection_id,
          provider_connections.provider AS provider,
          provider_connections.secret_ref_id AS secret_ref_id,
          provider_connections.metadata_json AS metadata_json,
          encrypted_secrets.reference AS encrypted_reference
        FROM provider_connections
        JOIN encrypted_secrets ON encrypted_secrets.id = provider_connections.secret_ref_id
        WHERE provider_connections.id = @connectionId
          AND provider_connections.deleted_at IS NULL
          AND provider_connections.status = 'CONNECTED'
          AND encrypted_secrets.deleted_at IS NULL
        LIMIT 1
      `
      )
      .get({ connectionId }) as
      | {
          connection_id: string;
          provider: string;
          secret_ref_id: string;
          encrypted_reference: string;
          metadata_json: string;
        }
      | undefined;

    return row
      ? {
          provider: ProviderTypeSchema.parse(row.provider),
          connectionId: row.connection_id,
          secretRefId: row.secret_ref_id,
          encryptedReference: row.encrypted_reference,
          metadata: parseJsonColumn(row.metadata_json, {})
        }
      : null;
  }

  createEncryptedSecretReference(input: {
    provider: SecretProviderType;
    keyName: string;
    encryptedReference: string;
    redactedHint: string;
    storageBackend?: "electron_safe_storage" | "os_keychain" | "env_ref" | "external_secret_manager";
  }): string {
    const id = randomUUID();
    const now = new Date().toISOString();
    this.db
      .prepare(
        `
        INSERT INTO encrypted_secrets (
          id, provider, key_name, storage_backend, reference, redacted_hint, created_at, updated_at
        )
        VALUES (
          @id, @provider, @keyName, @storageBackend, @reference, @redactedHint, @now, @now
        )
      `
      )
      .run({
        id,
        provider: SecretProviderTypeSchema.parse(input.provider),
        keyName: input.keyName,
        storageBackend: input.storageBackend ?? "electron_safe_storage",
        reference: input.encryptedReference,
        redactedHint: input.redactedHint,
        now
      });
    return id;
  }

  upsertConnection(input: {
    provider: ProviderType;
    displayName: string;
    status: "DISCONNECTED" | "CONNECTED" | "ERROR";
    secretRefId: string | null;
    metadata?: Record<string, unknown>;
  }): ProviderConnection {
    const provider = ProviderTypeSchema.parse(input.provider);
    const now = new Date().toISOString();
    const existing = this.db
      .prepare("SELECT * FROM provider_connections WHERE provider = ? AND deleted_at IS NULL ORDER BY created_at ASC LIMIT 1")
      .get(provider) as ProviderConnectionRow | undefined;
    const id = existing?.id ?? randomUUID();

    this.db
      .prepare(
        `
        INSERT INTO provider_connections (
          id, provider, display_name, status, secret_ref_id, metadata_json, created_at, updated_at
        )
        VALUES (
          @id, @provider, @displayName, @status, @secretRefId, @metadataJson, @createdAt, @updatedAt
        )
        ON CONFLICT(id) DO UPDATE SET
          display_name = excluded.display_name,
          status = excluded.status,
          secret_ref_id = excluded.secret_ref_id,
          metadata_json = excluded.metadata_json,
          updated_at = excluded.updated_at
      `
      )
      .run({
        id,
        provider,
        displayName: input.displayName,
        status: input.status,
        secretRefId: input.secretRefId,
        metadataJson: stringifyJsonColumn(input.metadata ?? {}),
        createdAt: existing?.created_at ?? now,
        updatedAt: now
      });

    const row = this.db.prepare("SELECT * FROM provider_connections WHERE id = ?").get(id) as ProviderConnectionRow;
    return mapProviderConnectionRow(row);
  }

  disconnectProvider(provider: ProviderType, metadata: Record<string, unknown> = {}): ProviderConnection | null {
    const existing = this.db
      .prepare("SELECT * FROM provider_connections WHERE provider = ? AND deleted_at IS NULL ORDER BY created_at ASC LIMIT 1")
      .get(ProviderTypeSchema.parse(provider)) as ProviderConnectionRow | undefined;
    if (!existing) {
      return null;
    }
    const now = new Date().toISOString();
    this.db
      .prepare(
        `
        UPDATE provider_connections
        SET status = 'DISCONNECTED',
            secret_ref_id = NULL,
            metadata_json = @metadataJson,
            updated_at = @updatedAt
        WHERE id = @id
      `
      )
      .run({
        id: existing.id,
        metadataJson: stringifyJsonColumn({ ...parseJsonColumn(existing.metadata_json, {}), ...metadata }),
        updatedAt: now
      });
    const row = this.db.prepare("SELECT * FROM provider_connections WHERE id = ?").get(existing.id) as ProviderConnectionRow;
    return mapProviderConnectionRow(row);
  }
}
