import { randomUUID } from "node:crypto";
import type { Database } from "better-sqlite3";

/** Low end of the 30 to 50 sends a day that keeps a personal mailbox out of spam folders. */
export const DEFAULT_OUTREACH_DAILY_CAP = 30;

const DAY_MS = 24 * 60 * 60 * 1000;

export interface OutreachContact {
  id: string;
  profileId: string;
  jobTargetId: string | null;
  name: string;
  email: string | null;
  company: string | null;
  roleTitle: string | null;
  linkedinUrl: string | null;
  notes: string;
  createdAt: string;
  updatedAt: string;
}

export interface OutreachMessage {
  id: string;
  contactId: string;
  jobTargetId: string | null;
  channel: "EMAIL" | "LINKEDIN";
  subject: string;
  body: string;
  status: "DRAFT" | "APPROVED" | "SENT" | "FAILED";
  approvedAt: string | null;
  sentAt: string | null;
  failureReason: string | null;
  createdAt: string;
  updatedAt: string;
}

export type OutreachSendResult =
  | { ok: true; message: OutreachMessage }
  | { ok: false; reason: "NOT_APPROVED" | "DAILY_CAP_REACHED" };

type ContactRow = {
  id: string;
  profile_id: string;
  job_target_id: string | null;
  name: string;
  email: string | null;
  company: string | null;
  role_title: string | null;
  linkedin_url: string | null;
  notes: string;
  created_at: string;
  updated_at: string;
};

type MessageRow = {
  id: string;
  contact_id: string;
  job_target_id: string | null;
  channel: string;
  subject: string;
  body: string;
  status: string;
  approved_at: string | null;
  sent_at: string | null;
  failure_reason: string | null;
  created_at: string;
  updated_at: string;
};

const parseContact = (row: ContactRow): OutreachContact => ({
  id: row.id,
  profileId: row.profile_id,
  jobTargetId: row.job_target_id,
  name: row.name,
  email: row.email,
  company: row.company,
  roleTitle: row.role_title,
  linkedinUrl: row.linkedin_url,
  notes: row.notes,
  createdAt: row.created_at,
  updatedAt: row.updated_at
});

const parseMessage = (row: MessageRow): OutreachMessage => ({
  id: row.id,
  contactId: row.contact_id,
  jobTargetId: row.job_target_id,
  channel: row.channel as OutreachMessage["channel"],
  subject: row.subject,
  body: row.body,
  status: row.status as OutreachMessage["status"],
  approvedAt: row.approved_at,
  sentAt: row.sent_at,
  failureReason: row.failure_reason,
  createdAt: row.created_at,
  updatedAt: row.updated_at
});

/**
 * Contacts, drafted messages and the send log. Nothing here sends mail: a sender
 * asks recordSend first, and only an APPROVED message under the daily cap is
 * marked SENT.
 */
export class OutreachRepository {
  constructor(private readonly db: Database) {}

  createContact(input: {
    profileId: string;
    name: string;
    jobTargetId?: string | null;
    email?: string | null;
    company?: string | null;
    roleTitle?: string | null;
    linkedinUrl?: string | null;
    notes?: string;
  }): OutreachContact {
    const id = randomUUID();
    const now = new Date().toISOString();
    this.db
      .prepare(
        `INSERT INTO outreach_contacts (id, profile_id, job_target_id, name, email, company, role_title, linkedin_url, notes, created_at, updated_at)
         VALUES (@id, @profileId, @jobTargetId, @name, @email, @company, @roleTitle, @linkedinUrl, @notes, @now, @now)`
      )
      .run({
        id,
        profileId: input.profileId,
        jobTargetId: input.jobTargetId ?? null,
        name: input.name,
        email: input.email ?? null,
        company: input.company ?? null,
        roleTitle: input.roleTitle ?? null,
        linkedinUrl: input.linkedinUrl ?? null,
        notes: input.notes ?? "",
        now
      });
    return parseContact(this.db.prepare("SELECT * FROM outreach_contacts WHERE id = ?").get(id) as ContactRow);
  }

  listContacts(profileId: string): OutreachContact[] {
    const rows = this.db
      .prepare("SELECT * FROM outreach_contacts WHERE profile_id = ? ORDER BY created_at ASC, rowid ASC")
      .all(profileId) as ContactRow[];
    return rows.map(parseContact);
  }

  createDraft(input: {
    contactId: string;
    channel: OutreachMessage["channel"];
    body: string;
    subject?: string;
    jobTargetId?: string | null;
  }): OutreachMessage {
    const id = randomUUID();
    const now = new Date().toISOString();
    this.db
      .prepare(
        `INSERT INTO outreach_messages (id, contact_id, job_target_id, channel, subject, body, status, created_at, updated_at)
         VALUES (@id, @contactId, @jobTargetId, @channel, @subject, @body, 'DRAFT', @now, @now)`
      )
      .run({
        id,
        contactId: input.contactId,
        jobTargetId: input.jobTargetId ?? null,
        channel: input.channel,
        subject: input.subject ?? "",
        body: input.body,
        now
      });
    return this.requireMessage(id);
  }

  getMessage(id: string): OutreachMessage | null {
    const row = this.db.prepare("SELECT * FROM outreach_messages WHERE id = ?").get(id) as MessageRow | undefined;
    return row ? parseMessage(row) : null;
  }

  listMessages(contactId: string): OutreachMessage[] {
    const rows = this.db
      .prepare("SELECT * FROM outreach_messages WHERE contact_id = ? ORDER BY created_at ASC, rowid ASC")
      .all(contactId) as MessageRow[];
    return rows.map(parseMessage);
  }

  /** Any edit, even to an approved message, needs a fresh approval. */
  updateDraft(id: string, input: { subject?: string; body?: string }): OutreachMessage {
    const changed = this.db
      .prepare(
        `UPDATE outreach_messages
         SET subject = COALESCE(@subject, subject), body = COALESCE(@body, body),
             status = 'DRAFT', approved_at = NULL, failure_reason = NULL, updated_at = @now
         WHERE id = @id AND status != 'SENT'`
      )
      .run({ id, subject: input.subject ?? null, body: input.body ?? null, now: new Date().toISOString() }).changes;
    if (changed === 0) {
      throw new Error("Only an unsent outreach message can be edited.");
    }
    return this.requireMessage(id);
  }

  approve(id: string, now: Date = new Date()): OutreachMessage {
    const stamp = now.toISOString();
    const changed = this.db
      .prepare(
        `UPDATE outreach_messages SET status = 'APPROVED', approved_at = @stamp, failure_reason = NULL, updated_at = @stamp
         WHERE id = @id AND status IN ('DRAFT', 'FAILED')`
      )
      .run({ id, stamp }).changes;
    if (changed === 0) {
      throw new Error("Only a draft or failed outreach message can be approved.");
    }
    return this.requireMessage(id);
  }

  sentInLast24Hours(now: Date = new Date()): number {
    const { c } = this.db
      .prepare("SELECT COUNT(*) AS c FROM outreach_messages WHERE status = 'SENT' AND sent_at > ?")
      .get(new Date(now.getTime() - DAY_MS).toISOString()) as { c: number };
    return c;
  }

  /** Marks an approved message SENT, unless that would pass the daily cap. */
  recordSend(id: string, options: { dailyCap?: number; now?: Date } = {}): OutreachSendResult {
    const now = options.now ?? new Date();
    const dailyCap = options.dailyCap ?? DEFAULT_OUTREACH_DAILY_CAP;
    return this.db.transaction((): OutreachSendResult => {
      if (this.getMessage(id)?.status !== "APPROVED") {
        return { ok: false, reason: "NOT_APPROVED" };
      }
      if (this.sentInLast24Hours(now) >= dailyCap) {
        return { ok: false, reason: "DAILY_CAP_REACHED" };
      }
      const stamp = now.toISOString();
      this.db
        .prepare("UPDATE outreach_messages SET status = 'SENT', sent_at = @stamp, updated_at = @stamp WHERE id = @id")
        .run({ id, stamp });
      return { ok: true, message: this.requireMessage(id) };
    })();
  }

  recordFailure(id: string, reason: string): OutreachMessage {
    const changed = this.db
      .prepare(
        `UPDATE outreach_messages SET status = 'FAILED', failure_reason = @reason, updated_at = @now
         WHERE id = @id AND status = 'APPROVED'`
      )
      .run({ id, reason, now: new Date().toISOString() }).changes;
    if (changed === 0) {
      throw new Error("Only an approved outreach message can fail to send.");
    }
    return this.requireMessage(id);
  }

  private requireMessage(id: string): OutreachMessage {
    const message = this.getMessage(id);
    if (!message) {
      throw new Error(`Outreach message ${id} not found.`);
    }
    return message;
  }
}
