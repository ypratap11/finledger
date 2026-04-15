import pg from "pg";

export const pool = new pg.Pool({
  connectionString: process.env.DATABASE_URL
    ?? "postgresql://finledger:finledger@localhost:5432/finledger",
});

export async function insertSourceEvent(args: {
  source: string;
  eventType: string;
  externalId: string;
  payload: unknown;
}): Promise<"inserted" | "duplicate"> {
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const prevRes = await client.query<{ row_hash: Buffer }>(
      "SELECT row_hash FROM inbox.source_events ORDER BY received_at DESC, id DESC LIMIT 1"
    );
    const prevHash: Buffer = prevRes.rows[0]?.row_hash ?? Buffer.alloc(32);
    const canonical = Buffer.from(canonicalJson(args.payload), "utf-8");
    const rowHash = await computeRowHash(prevHash, args.source, args.externalId, canonical);
    try {
      await client.query(
        `INSERT INTO inbox.source_events
           (source, event_type, external_id, idempotency_key, payload, prev_hash, row_hash)
         VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7)`,
        [
          args.source,
          args.eventType,
          args.externalId,
          `${args.source}:${args.externalId}`,
          JSON.stringify(args.payload),
          prevHash,
          rowHash,
        ],
      );
      await client.query("COMMIT");
      return "inserted";
    } catch (err: any) {
      await client.query("ROLLBACK");
      if (err.code === "23505") return "duplicate";
      throw err;
    }
  } finally {
    client.release();
  }
}

// Canonical JSON: sorted keys at every level, no whitespace.
// Must match Python's json.dumps(obj, sort_keys=True, separators=(",", ":")).
function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return "[" + value.map(canonicalJson).join(",") + "]";
  const keys = Object.keys(value as object).sort();
  return "{" + keys.map((k) => JSON.stringify(k) + ":" + canonicalJson((value as any)[k])).join(",") + "}";
}

async function computeRowHash(
  prev: Buffer, source: string, externalId: string, payload: Buffer,
): Promise<Buffer> {
  const { createHash } = await import("node:crypto");
  const h = createHash("sha256");
  h.update(prev);
  h.update(source);
  h.update(Buffer.from([0]));
  h.update(externalId);
  h.update(Buffer.from([0]));
  h.update(payload);
  return h.digest();
}
