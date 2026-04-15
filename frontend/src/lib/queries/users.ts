import { getPool } from "@/lib/db";
import type { RowDataPacket } from "mysql2";
import type { User, UserProfile, UserPreferences, UserStats, ModelStat, DailyStatRow, ToolStat } from "@/types";

export async function getUserByEmail(email: string, instance?: string): Promise<User | null> {
  const pool = getPool();
  const [rows] = await pool.execute<RowDataPacket[]>(
    "SELECT user_id, email, display_name, telegram_username, is_allowed, allowed_instances FROM users WHERE email = ? AND is_allowed = TRUE",
    [email]
  );
  const user = rows[0] as (User & { allowed_instances?: string | string[] | null }) | undefined;
  if (!user) return null;

  // If an instance is specified, check allowed_instances
  if (instance) {
    let instances: string[] = [];
    if (typeof user.allowed_instances === "string") {
      try { instances = JSON.parse(user.allowed_instances); } catch { instances = []; }
    } else if (Array.isArray(user.allowed_instances)) {
      instances = user.allowed_instances;
    }
    // If allowed_instances is set (non-empty), enforce it; null/empty = allow all (backwards compat)
    if (instances.length > 0 && !instances.includes(instance)) {
      return null;
    }
  }

  return user;
}

export async function getUserByTelegramId(telegramId: string, instance?: string): Promise<User | null> {
  const pool = getPool();
  const [rows] = await pool.execute<RowDataPacket[]>(
    "SELECT user_id, email, display_name, telegram_username, is_allowed, allowed_instances FROM users WHERE user_id = ? AND is_allowed = TRUE",
    [telegramId]
  );
  const user = rows[0] as (User & { allowed_instances?: string | string[] | null }) | undefined;
  if (!user) return null;

  if (instance) {
    let instances: string[] = [];
    if (typeof user.allowed_instances === "string") {
      try { instances = JSON.parse(user.allowed_instances); } catch { instances = []; }
    } else if (Array.isArray(user.allowed_instances)) {
      instances = user.allowed_instances;
    }
    if (instances.length > 0 && !instances.includes(instance)) {
      return null;
    }
  }

  return user;
}

export async function getUserById(userId: number): Promise<User | null> {
  const pool = getPool();
  const [rows] = await pool.execute<RowDataPacket[]>(
    "SELECT user_id, email, display_name, telegram_username, is_allowed FROM users WHERE user_id = ? AND is_allowed = TRUE",
    [userId]
  );
  return (rows[0] as User) || null;
}

// ── Full profile including preferences ────────────────────────────────────
export async function getUserProfile(userId: number): Promise<UserProfile | null> {
  const pool = getPool();
  const [rows] = await pool.execute<RowDataPacket[]>(
    `SELECT user_id, email, display_name, telegram_username,
            total_cost, message_count, session_count, preferences
     FROM users WHERE user_id = ? AND is_allowed = TRUE`,
    [userId]
  );
  if (!rows[0]) return null;

  const row = rows[0];
  const rawPrefs = typeof row.preferences === "string"
    ? JSON.parse(row.preferences)
    : (row.preferences ?? {});

  const defaults: UserPreferences = {
    permission_mode: "yolo",
    model: "default",
    thinking: false,
    max_turns: 20,
    budget: null,
    verbose: 1,
    working_directory: "/root/workspace",
  };

  return {
    user_id: row.user_id,
    email: row.email,
    display_name: row.display_name,
    telegram_username: row.telegram_username,
    total_cost: parseFloat(row.total_cost ?? 0),
    message_count: row.message_count ?? 0,
    session_count: row.session_count ?? 0,
    preferences: { ...defaults, ...rawPrefs },
  };
}

// ── Update profile fields ─────────────────────────────────────────────────
export async function updateUserProfile(
  userId: number,
  updates: {
    display_name?: string;
    preferences?: Partial<UserPreferences>;
  }
): Promise<void> {
  const pool = getPool();

  if (updates.display_name !== undefined) {
    await pool.execute(
      "UPDATE users SET display_name = ? WHERE user_id = ?",
      [updates.display_name || null, userId]
    );
  }

  if (updates.preferences && Object.keys(updates.preferences).length > 0) {
    // Merge into existing JSON — MySQL JSON_MERGE_PATCH for atomic update
    const jsonPatch = JSON.stringify(updates.preferences);
    await pool.execute(
      `UPDATE users
       SET preferences = JSON_MERGE_PATCH(COALESCE(preferences, '{}'), ?)
       WHERE user_id = ?`,
      [jsonPatch, userId]
    );
  }
}

// ── Statistics ────────────────────────────────────────────────────────────
export async function getUserStats(userId: number): Promise<UserStats> {
  const pool = getPool();

  // Aggregated totals
  const [totals] = await pool.execute<RowDataPacket[]>(
    `SELECT
       message_count,
       session_count,
       total_cost
     FROM users WHERE user_id = ?`,
    [userId]
  );

  const [tokens] = await pool.execute<RowDataPacket[]>(
    `SELECT
       COALESCE(SUM(input_tokens), 0) AS input_tokens,
       COALESCE(SUM(output_tokens), 0) AS output_tokens,
       COALESCE(SUM(cache_creation_tokens), 0) AS cache_creation_tokens,
       COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens
     FROM messages WHERE user_id = ? AND error IS NULL`,
    [userId]
  );

  const [byModel] = await pool.execute<RowDataPacket[]>(
    `SELECT
       COALESCE(model, 'unknown') AS model,
       COUNT(*) AS messages,
       COALESCE(SUM(cost), 0) AS cost,
       COALESCE(SUM(input_tokens), 0) AS input_tokens,
       COALESCE(SUM(output_tokens), 0) AS output_tokens,
       COALESCE(SUM(cache_creation_tokens), 0) AS cache_creation_tokens,
       COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens
     FROM messages
     WHERE user_id = ? AND error IS NULL
     GROUP BY model
     ORDER BY cost DESC`,
    [userId]
  );

  const t = totals[0] ?? {};
  const tk = tokens[0] ?? {};

  return {
    total_messages: t.message_count ?? 0,
    total_sessions: t.session_count ?? 0,
    total_cost: parseFloat(t.total_cost ?? 0),
    input_tokens: parseInt(tk.input_tokens ?? 0),
    output_tokens: parseInt(tk.output_tokens ?? 0),
    cache_creation_tokens: parseInt(tk.cache_creation_tokens ?? 0),
    cache_read_tokens: parseInt(tk.cache_read_tokens ?? 0),
    by_model: (byModel as ModelStat[]).map((row) => ({
      model: row.model,
      messages: parseInt(String(row.messages)),
      cost: parseFloat(String(row.cost)),
      input_tokens: parseInt(String(row.input_tokens)),
      output_tokens: parseInt(String(row.output_tokens)),
      cache_creation_tokens: parseInt(String(row.cache_creation_tokens)),
      cache_read_tokens: parseInt(String(row.cache_read_tokens)),
    })),
  };
}

export async function getDailyStats(userId: number): Promise<DailyStatRow[]> {
  const pool = getPool();
  const [rows] = await pool.execute<RowDataPacket[]>(
    `SELECT
       DATE(timestamp) AS date,
       COALESCE(model, 'unknown') AS model,
       COALESCE(SUM(input_tokens), 0) AS input_tokens,
       COALESCE(SUM(output_tokens), 0) AS output_tokens,
       COALESCE(SUM(cache_creation_tokens), 0) AS cache_creation_tokens,
       COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
       COALESCE(SUM(cost), 0) AS cost,
       COUNT(*) AS messages
     FROM messages
     WHERE user_id = ? AND response IS NOT NULL
     GROUP BY DATE(timestamp), model
     ORDER BY date ASC`,
    [userId]
  );
  return (rows as RowDataPacket[]).map((r) => ({
    date: r.date instanceof Date ? r.date.toISOString().slice(0, 10) : String(r.date),
    model: r.model,
    input_tokens: Number(r.input_tokens),
    output_tokens: Number(r.output_tokens),
    cache_creation_tokens: Number(r.cache_creation_tokens),
    cache_read_tokens: Number(r.cache_read_tokens),
    cost: Number(r.cost),
    messages: Number(r.messages),
  }));
}

// ── TTS user settings ─────────────────────────────────────────────────────

export interface TTSSettings {
  provider: string;
  voice: string;
  style_prompt: string | null;
  model: string | null;
  output_format: string;
}

const TTS_DEFAULTS: TTSSettings = {
  provider: "gemini",
  voice: "Puck",
  style_prompt: null,
  model: null,
  output_format: "oga",
};

export async function getUserTTSSettings(userId: number): Promise<TTSSettings> {
  const pool = getPool();
  const [rows] = await pool.execute<RowDataPacket[]>(
    "SELECT provider, voice, style_prompt, model, output_format FROM user_tts_settings WHERE user_id = ?",
    [userId]
  );
  if (!rows[0]) return { ...TTS_DEFAULTS };
  const r = rows[0];
  return {
    provider: r.provider ?? TTS_DEFAULTS.provider,
    voice: r.voice ?? TTS_DEFAULTS.voice,
    style_prompt: r.style_prompt ?? null,
    model: r.model ?? null,
    output_format: r.output_format ?? TTS_DEFAULTS.output_format,
  };
}

export async function upsertUserTTSSettings(
  userId: number,
  settings: Partial<TTSSettings>
): Promise<TTSSettings> {
  const pool = getPool();
  // Fetch current to merge
  const current = await getUserTTSSettings(userId);
  const merged: TTSSettings = {
    provider: settings.provider ?? current.provider,
    voice: settings.voice ?? current.voice,
    style_prompt: "style_prompt" in settings ? (settings.style_prompt ?? null) : current.style_prompt,
    model: "model" in settings ? (settings.model ?? null) : current.model,
    output_format: settings.output_format ?? current.output_format,
  };
  await pool.execute(
    `INSERT INTO user_tts_settings (user_id, provider, voice, style_prompt, model, output_format)
     VALUES (?, ?, ?, ?, ?, ?)
     ON DUPLICATE KEY UPDATE
       provider = VALUES(provider),
       voice = VALUES(voice),
       style_prompt = VALUES(style_prompt),
       model = VALUES(model),
       output_format = VALUES(output_format)`,
    [userId, merged.provider, merged.voice, merged.style_prompt, merged.model, merged.output_format]
  );
  return merged;
}

export async function getToolStats(userId: number): Promise<ToolStat[]> {
  const pool = getPool();
  const [rows] = await pool.execute<RowDataPacket[]>(
    `SELECT tu.tool_name, COUNT(*) AS count
     FROM tool_usage tu
     JOIN sessions s ON tu.session_id = s.session_id
     WHERE s.user_id = ?
     GROUP BY tu.tool_name
     ORDER BY count DESC
     LIMIT 15`,
    [userId]
  );
  return (rows as RowDataPacket[]).map((r) => ({
    tool_name: String(r.tool_name),
    count: Number(r.count),
  }));
}
