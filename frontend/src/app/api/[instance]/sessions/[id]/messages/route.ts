import { NextRequest, NextResponse } from "next/server";
import { getSessionUser } from "@/lib/auth";
import { isValidInstance } from "@/lib/instances";
import { getPool } from "@/lib/db";
import type { RowDataPacket } from "mysql2";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ instance: string; id: string }> }
) {
  const { instance, id } = await params;

  if (!isValidInstance(instance)) {
    return NextResponse.json({ error: "Invalid instance." }, { status: 400 });
  }

  const user = await getSessionUser();
  if (!user) {
    return NextResponse.json({ error: "Not logged in." }, { status: 401 });
  }

  try {
    const pool = getPool();

    // Verify session belongs to this user
    const [sessionRows] = await pool.execute<RowDataPacket[]>(
      "SELECT session_id FROM sessions WHERE session_id = ? AND user_id = ?",
      [id, user.user_id]
    );
    if (!sessionRows[0]) {
      return NextResponse.json({ error: "Session not found." }, { status: 404 });
    }

    // Fetch messages ordered chronologically (include tools_json for UI)
    const [rows] = await pool.execute<RowDataPacket[]>(
      `SELECT message_id, timestamp, prompt, response, error, tools_json
       FROM messages
       WHERE session_id = ?
       ORDER BY timestamp ASC, message_id ASC`,
      [id]
    );

    // Each DB row = one user turn + one assistant turn
    const messages: Array<{
      id: string;
      role: "user" | "assistant";
      content: string;
      timestamp: string;
      tools?: unknown[];
    }> = [];

    for (const row of rows) {
      const ts = row.timestamp instanceof Date
        ? row.timestamp.toISOString()
        : String(row.timestamp);

      if (row.prompt) {
        messages.push({
          id: `msg-${row.message_id}-user`,
          role: "user",
          content: row.prompt,
          timestamp: ts,
        });
      }

      // Always emit an assistant message when a prompt exists — even if the
      // response text is empty (the agent may have only used tools).  This
      // matches Telegram behaviour where a progress message is always sent.
      if (row.prompt || row.response || row.error) {
        // Parse tools_json from DB
        let tools: unknown[] | undefined;
        if (row.tools_json) {
          try {
            tools = typeof row.tools_json === "string"
              ? JSON.parse(row.tools_json)
              : row.tools_json;
          } catch {
            tools = undefined;
          }
        }

        const msg: typeof messages[number] = {
          id: `msg-${row.message_id}-assistant`,
          role: "assistant",
          content: row.response || (row.error ? `⚠ Error: ${row.error}` : ""),
          timestamp: ts,
        };
        if (tools && tools.length > 0) {
          msg.tools = tools;
        }
        messages.push(msg);
      }
    }

    return NextResponse.json(messages);
  } catch (e) {
    console.error("messages GET error", e);
    return NextResponse.json({ error: "Datenbankfehler." }, { status: 500 });
  }
}
