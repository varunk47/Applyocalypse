import type { Database } from "better-sqlite3";
import { randomUUID } from "node:crypto";
import { QueueItemSchema } from "@applyocalypse/shared-schemas";
import type { z } from "zod";

export type QueueItem = z.infer<typeof QueueItemSchema>;

type QueueRow = {
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
};

const mapQueueRow = (row: QueueRow): QueueItem =>
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

export class QueueRepository {
  constructor(private readonly db: Database) {}

  enqueue(profileId: string, jobTargetId: string, priority = 0, autoSubmitEnabled = false): QueueItem {
    const now = new Date().toISOString();
    const id = randomUUID();
    this.db
      .prepare(
        `
        INSERT INTO queue_items (id, profile_id, job_target_id, status, priority, auto_submit_enabled, created_at, updated_at)
        VALUES (@id, @profileId, @jobTargetId, 'PENDING', @priority, @autoSubmitEnabled, @now, @now)
      `
      )
      .run({ id, profileId, jobTargetId, priority, autoSubmitEnabled: autoSubmitEnabled ? 1 : 0, now });

    return this.getById(id);
  }

  getById(id: string): QueueItem {
    const row = this.db.prepare("SELECT * FROM queue_items WHERE id = ?").get(id) as QueueRow | undefined;
    if (!row) {
      throw new Error(`Queue item not found: ${id}`);
    }
    return mapQueueRow(row);
  }

  list(limit = 50, offset = 0): QueueItem[] {
    const rows = this.db
      .prepare("SELECT * FROM queue_items WHERE deleted_at IS NULL ORDER BY priority DESC, created_at ASC LIMIT ? OFFSET ?")
      .all(limit, offset) as QueueRow[];
    return rows.map(mapQueueRow);
  }

  count(): number {
    const row = this.db.prepare("SELECT COUNT(*) AS count FROM queue_items WHERE deleted_at IS NULL").get() as { count: number };
    return row.count;
  }

  claimNext(workerId: string, leaseMs: number, maxConcurrent = 2): QueueItem | null {
    const now = Date.now();
    const nowIso = new Date(now).toISOString();
    const leaseIso = new Date(now + leaseMs).toISOString();

    const claim = this.db.transaction(() => {
      const active = this.db
        .prepare(
          `
          SELECT COUNT(*) AS count
          FROM queue_items
          WHERE claimed_by IS NOT NULL
            AND deleted_at IS NULL
            AND (lease_expires_at IS NULL OR lease_expires_at >= @nowIso)
            AND status NOT IN ('PENDING','SUBMITTED','COMPLETED','FAILED','CANCELLED')
        `
        )
        .get({ nowIso }) as { count: number };

      if (active.count >= maxConcurrent) {
        return null;
      }

      this.db
        .prepare(
          `
          UPDATE queue_items
          SET status = 'FAILED',
              claimed_by = NULL,
              lease_expires_at = NULL,
              heartbeat_at = NULL,
              updated_at = @nowIso
          WHERE deleted_at IS NULL
            AND attempts >= max_attempts
            AND (
              status = 'PENDING'
              OR (status = 'CLAIMED' AND lease_expires_at IS NOT NULL AND lease_expires_at < @nowIso)
            )
        `
        )
        .run({ nowIso });

      const row = this.db
        .prepare(
          `
          SELECT * FROM queue_items
          WHERE deleted_at IS NULL
            AND (
              (status = 'PENDING' AND attempts < max_attempts)
              OR (status = 'CLAIMED' AND attempts < max_attempts AND lease_expires_at IS NOT NULL AND lease_expires_at < @nowIso)
            )
          ORDER BY priority DESC, created_at ASC
          LIMIT 1
        `
        )
        .get({ nowIso }) as QueueRow | undefined;

      if (!row) {
        return null;
      }

      this.db
        .prepare(
          `
          UPDATE queue_items
          SET status = 'CLAIMED',
              attempts = attempts + 1,
              claimed_by = @workerId,
              lease_expires_at = @leaseIso,
              heartbeat_at = @nowIso,
              updated_at = @nowIso
          WHERE id = @id
        `
        )
        .run({ id: row.id, workerId, leaseIso, nowIso });

      return this.getById(row.id);
    });

    return claim();
  }

  heartbeat(id: string, leaseMs: number): void {
    const now = Date.now();
    this.db
      .prepare(
        `
        UPDATE queue_items
        SET heartbeat_at = @heartbeatAt,
            lease_expires_at = @leaseExpiresAt,
            updated_at = @heartbeatAt
        WHERE id = @id
      `
      )
      .run({
        id,
        heartbeatAt: new Date(now).toISOString(),
        leaseExpiresAt: new Date(now + leaseMs).toISOString()
      });
  }

  recoverExpired(nowIso = new Date().toISOString()): number {
    const result = this.db
      .prepare(
        `
        UPDATE queue_items
        SET status = 'PENDING',
            claimed_by = NULL,
            lease_expires_at = NULL,
            updated_at = @nowIso
        WHERE status = 'CLAIMED'
          AND lease_expires_at IS NOT NULL
          AND lease_expires_at < @nowIso
      `
      )
      .run({ nowIso });
    return result.changes;
  }
}
