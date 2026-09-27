import { randomUUID } from "node:crypto";
import type { Database } from "better-sqlite3";

/** Same keys as the canonical profile's address, so the worker can swap one in. */
export interface WorkerAddress {
  label: string;
  addressLine1: string;
  addressLine2: string;
  city: string;
  state: string;
  postalCode: string;
  country: string;
}

export interface ProfileAddress extends WorkerAddress {
  id: string;
  profileId: string;
  createdAt: string;
  updatedAt: string;
}

type ProfileAddressRow = {
  id: string;
  profile_id: string;
  label: string;
  address_line1: string;
  address_line2: string;
  city: string;
  state: string;
  postal_code: string;
  country: string;
  created_at: string;
  updated_at: string;
};

const toWorker = (row: ProfileAddressRow): WorkerAddress => ({
  label: row.label,
  addressLine1: row.address_line1,
  addressLine2: row.address_line2,
  city: row.city,
  state: row.state,
  postalCode: row.postal_code,
  country: row.country
});

const parseRow = (row: ProfileAddressRow): ProfileAddress => ({
  id: row.id,
  profileId: row.profile_id,
  ...toWorker(row),
  createdAt: row.created_at,
  updatedAt: row.updated_at
});

export class ProfileAddressRepository {
  constructor(private readonly db: Database) {}

  private rows(profileId: string): ProfileAddressRow[] {
    return this.db
      .prepare("SELECT * FROM profile_addresses WHERE profile_id = ? ORDER BY created_at ASC, rowid ASC")
      .all(profileId) as ProfileAddressRow[];
  }

  listByProfile(profileId: string): ProfileAddress[] {
    return this.rows(profileId).map(parseRow);
  }

  workerAddresses(profileId: string): WorkerAddress[] {
    return this.rows(profileId).map(toWorker);
  }

  upsert(input: { id?: string | undefined; profileId: string } & { [key in keyof WorkerAddress]?: string | undefined }): ProfileAddress {
    const city = (input.city ?? "").trim();
    if (!city) {
      throw new Error("An address needs a city.");
    }
    const id = input.id ?? randomUUID();
    const now = new Date().toISOString();
    this.db
      .prepare(
        `INSERT INTO profile_addresses
           (id, profile_id, label, address_line1, address_line2, city, state, postal_code, country, created_at, updated_at)
         VALUES (@id, @profileId, @label, @addressLine1, @addressLine2, @city, @state, @postalCode, @country, @now, @now)
         ON CONFLICT(id) DO UPDATE SET
           label = excluded.label,
           address_line1 = excluded.address_line1,
           address_line2 = excluded.address_line2,
           city = excluded.city,
           state = excluded.state,
           postal_code = excluded.postal_code,
           country = excluded.country,
           updated_at = excluded.updated_at
         WHERE profile_addresses.profile_id = excluded.profile_id`
      )
      .run({
        id,
        profileId: input.profileId,
        label: (input.label ?? "").trim(),
        addressLine1: (input.addressLine1 ?? "").trim(),
        addressLine2: (input.addressLine2 ?? "").trim(),
        city,
        state: (input.state ?? "").trim(),
        postalCode: (input.postalCode ?? "").trim(),
        country: (input.country ?? "").trim(),
        now
      });
    const row = this.db.prepare("SELECT * FROM profile_addresses WHERE id = ? AND profile_id = ?").get(id, input.profileId) as
      | ProfileAddressRow
      | undefined;
    if (!row) {
      throw new Error("Address belongs to another profile.");
    }
    return parseRow(row);
  }

  delete(id: string): boolean {
    return this.db.prepare("DELETE FROM profile_addresses WHERE id = ?").run(id).changes > 0;
  }
}
