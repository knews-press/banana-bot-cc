import { getPool } from "@/lib/db";
import type { RowDataPacket } from "mysql2";

export async function getApiKeyForUser(userId: number): Promise<string | null> {
  const pool = getPool();
  const [rows] = await pool.execute<RowDataPacket[]>(
    "SELECT api_key FROM api_keys WHERE user_id = ? AND is_active = TRUE ORDER BY created_at DESC LIMIT 1",
    [userId]
  );
  return rows[0]?.api_key || null;
}

export async function createApiKeyForUser(
  userId: number,
  name: string,
  key: string
): Promise<void> {
  const pool = getPool();
  await pool.execute(
    "INSERT INTO api_keys (api_key, user_id, name) VALUES (?, ?, ?)",
    [key, userId, name]
  );
}
