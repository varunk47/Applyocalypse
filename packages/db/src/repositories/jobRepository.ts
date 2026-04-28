import type { Database } from "better-sqlite3";
import { randomUUID } from "node:crypto";
import { JobTargetSchema, QueueItemSchema } from "@applyocalypse/shared-schemas";
import type { z } from "zod";

export type JobTarget = z.infer<typeof JobTargetSchema>;
export type EnqueuedQueueItem = z.infer<typeof QueueItemSchema>;

type EnqueueInput = {
  profileId: string;
  items: Array<{ sourceKind: "URL" | "TEXT"; sourceValue: string; autoSubmitEnabled?: boolean }>;
};

const mapQueueRow = (row: {
  id: string;
  profile_id: string;
  job_target_id: string;
  status: string;
  auto_submit_enabled: number;
  priority: number;
  attempts: number;
  max_attempts: number;
  claimed_by: string | null;
  lease_expires_at: string | null;
  heartbeat_at: string | null;
  created_at: string;
  updated_at: string;
}): EnqueuedQueueItem =>
  QueueItemSchema.parse({
    id: row.id,
    profileId: row.profile_id,
    jobTargetId: row.job_target_id,
    status: row.status,
    autoSubmitEnabled: row.auto_submit_enabled === 1,
    priority: row.priority,
    attempts: row.attempts,
    maxAttempts: row.max_attempts,
    claimedBy: row.claimed_by,
    leaseExpiresAt: row.lease_expires_at,
    heartbeatAt: row.heartbeat_at,
    createdAt: row.created_at,
    updatedAt: row.updated_at
  });

export class JobRepository {
  constructor(private readonly db: Database) {}

  getTargetById(id: string): JobTarget {
    const row = this.db.prepare("SELECT * FROM job_targets WHERE id = ? AND deleted_at IS NULL").get(id) as
      | {
          id: string;
          source_kind: "URL" | "TEXT";
          source_value: string;
          company: string | null;
          role: string | null;
          location: string | null;
          portal: string | null;
          status: string;
          created_at: string;
          updated_at: string;
        }
      | undefined;
    if (!row) {
      throw new Error(`Job target not found: ${id}`);
    }
    return JobTargetSchema.parse({
      id: row.id,
      sourceKind: row.source_kind,
      sourceValue: row.source_value,
      company: row.company,
      role: row.role,
      location: row.location,
      portal: row.portal,
      status: row.status,
      createdAt: row.created_at,
      updatedAt: row.updated_at
    });
  }

  enqueueTargets(input: EnqueueInput): { jobTargets: JobTarget[]; queueItems: EnqueuedQueueItem[] } {
    const transaction = this.db.transaction(() => {
      const jobTargets: JobTarget[] = [];
      const queueItems: EnqueuedQueueItem[] = [];
      const now = new Date().toISOString();

      for (const item of input.items) {
        const targetId = randomUUID();
        const queueItemId = randomUUID();

        this.db
          .prepare(
            `
            INSERT INTO job_targets (id, source_kind, source_value, status, created_at, updated_at)
            VALUES (@id, @sourceKind, @sourceValue, 'PENDING', @now, @now)
          `
          )
          .run({ id: targetId, sourceKind: item.sourceKind, sourceValue: item.sourceValue, now });

        this.db
          .prepare(
            `
            INSERT INTO queue_items (id, profile_id, job_target_id, status, auto_submit_enabled, created_at, updated_at)
            VALUES (@id, @profileId, @jobTargetId, 'PENDING', @autoSubmitEnabled, @now, @now)
          `
          )
          .run({
            id: queueItemId,
            profileId: input.profileId,
            jobTargetId: targetId,
            autoSubmitEnabled: item.autoSubmitEnabled ? 1 : 0,
            now
          });

        jobTargets.push(
          JobTargetSchema.parse({
            id: targetId,
            sourceKind: item.sourceKind,
            sourceValue: item.sourceValue,
            company: null,
            role: null,
            location: null,
            portal: null,
            status: "PENDING",
            createdAt: now,
            updatedAt: now
          })
        );

        const queueRow = this.db.prepare("SELECT * FROM queue_items WHERE id = ?").get(queueItemId) as Parameters<typeof mapQueueRow>[0];
        queueItems.push(mapQueueRow(queueRow));
      }

      return { jobTargets, queueItems };
    });

    return transaction();
  }

  listTargets(limit = 50, offset = 0): JobTarget[] {
    const rows = this.db
      .prepare("SELECT * FROM job_targets WHERE deleted_at IS NULL ORDER BY created_at DESC LIMIT ? OFFSET ?")
      .all(limit, offset) as Array<{
      id: string;
      source_kind: "URL" | "TEXT";
      source_value: string;
      company: string | null;
      role: string | null;
      location: string | null;
      portal: string | null;
      status: string;
      created_at: string;
      updated_at: string;
    }>;

    return rows.map((row) =>
      JobTargetSchema.parse({
        id: row.id,
        sourceKind: row.source_kind,
        sourceValue: row.source_value,
        company: row.company,
        role: row.role,
        location: row.location,
        portal: row.portal,
        status: row.status,
        createdAt: row.created_at,
        updatedAt: row.updated_at
      })
    );
  }
}
