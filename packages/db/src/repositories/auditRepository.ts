import type { Database } from "better-sqlite3";
import { randomUUID } from "node:crypto";
import { stringifyJsonColumn } from "../json";

export type AuditLogInput = {
  actor?: string;
  action: string;
  entityType: string;
  entityId?: string | null;
  metadata?: Record<string, unknown>;
};

export class AuditRepository {
  constructor(private readonly db: Database) {}

  append(input: AuditLogInput): string {
    const id = randomUUID();
    this.db
      .prepare(
        `
        INSERT INTO audit_logs (id, actor, action, entity_type, entity_id, metadata_json, created_at)
        VALUES (@id, @actor, @action, @entityType, @entityId, @metadataJson, @createdAt)
      `
      )
      .run({
        id,
        actor: input.actor ?? "local_user",
        action: input.action,
        entityType: input.entityType,
        entityId: input.entityId ?? null,
        metadataJson: stringifyJsonColumn(input.metadata ?? {}),
        createdAt: new Date().toISOString()
      });
    return id;
  }
}
