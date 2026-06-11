import { randomUUID } from "node:crypto";
import type { Database } from "better-sqlite3";

export interface ChatMessage {
  id: string;
  batchId: string | null;
  runId: string | null;
  jobId: string | null;
  role: "USER" | "SYSTEM";
  kind: "TEXT" | "JOB_CARD" | "BATCH_HEADER";
  content: string;
  metadata: Record<string, unknown>;
  createdAt: string;
}

type ChatMessageRow = {
  id: string;
  batch_id: string | null;
  run_id: string | null;
  job_id: string | null;
  role: string;
  kind: string;
  content: string;
  metadata_json: string;
  created_at: string;
};

const parseRow = (row: ChatMessageRow): ChatMessage => ({
  id: row.id,
  batchId: row.batch_id,
  runId: row.run_id,
  jobId: row.job_id,
  role: row.role as ChatMessage["role"],
  kind: row.kind as ChatMessage["kind"],
  content: row.content,
  metadata: JSON.parse(row.metadata_json) as Record<string, unknown>,
  createdAt: row.created_at
});

export class ChatRepository {
  constructor(private readonly db: Database) {}

  appendMessage(input: {
    batchId?: string | null;
    runId?: string | null;
    jobId?: string | null;
    role: ChatMessage["role"];
    kind: ChatMessage["kind"];
    content: string;
    metadata?: Record<string, unknown>;
  }): ChatMessage {
    const id = randomUUID();
    const now = new Date().toISOString();
    this.db
      .prepare(
        `INSERT INTO chat_messages (id, batch_id, run_id, job_id, role, kind, content, metadata_json, created_at)
         VALUES (@id, @batchId, @runId, @jobId, @role, @kind, @content, @metadataJson, @createdAt)`
      )
      .run({
        id,
        batchId: input.batchId ?? null,
        runId: input.runId ?? null,
        jobId: input.jobId ?? null,
        role: input.role,
        kind: input.kind,
        content: input.content,
        metadataJson: JSON.stringify(input.metadata ?? {}),
        createdAt: now
      });
    return parseRow(
      this.db.prepare("SELECT * FROM chat_messages WHERE id = ?").get(id) as ChatMessageRow
    );
  }

  list(limit = 200, offset = 0): { items: ChatMessage[]; total: number } {
    const { c: total } = this.db
      .prepare("SELECT COUNT(*) AS c FROM chat_messages")
      .get() as { c: number };
    const rows = this.db
      .prepare("SELECT * FROM chat_messages ORDER BY created_at ASC LIMIT ? OFFSET ?")
      .all(limit, offset) as ChatMessageRow[];
    return { items: rows.map(parseRow), total };
  }
}
