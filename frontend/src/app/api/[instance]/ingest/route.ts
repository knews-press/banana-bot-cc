import { NextRequest, NextResponse } from "next/server";
import { getAuthenticatedClient } from "@/lib/proxy";

/**
 * POST /api/[instance]/ingest
 *
 * Browser extension endpoint: receives a page's extracted text and saves
 * it as a memory via the backend, which runs the full NER pipeline.
 *
 * Body:
 *   name        — stable identifier, typically the page URL
 *   content     — full article text (extracted by Readability.js in extension)
 *   title       — human-readable article title (used as description prefix)
 *   memory_type — defaults to "Article"
 *   tags        — optional string array
 *
 * Returns:
 *   { id, version, enrichment: { nodes, edges, entities } }
 */
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ instance: string }> }
) {
  const { instance } = await params;
  const [client, error] = await getAuthenticatedClient(instance);
  if (error || !client) return error ?? NextResponse.json({ error: "No client" }, { status: 500 });

  let body: {
    name?: string;
    content?: string;
    title?: string;
    memory_type?: string;
    tags?: string[];
  };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON." }, { status: 400 });
  }

  if (!body.name || !body.content) {
    return NextResponse.json({ error: "name und content sind erforderlich." }, { status: 400 });
  }

  // Build a human-readable description from title + URL
  const description = body.title
    ? `${body.title} — ${body.name}`
    : body.name;

  try {
    const response = await client.ingestMemory({
      name: body.name,
      memory_type: body.memory_type ?? "Article",
      description,
      content: body.content,
      tags: body.tags,
    });
    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch {
    return NextResponse.json({ error: "Backend nicht erreichbar." }, { status: 502 });
  }
}
