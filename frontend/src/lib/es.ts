const ES_URL = process.env.ES_URL || "http://elasticsearch:9200";
const MEMORIES_INDEX = "claude-memories";
const HISTORY_INDEX = "claude-memories-history";

export interface EsMemory {
  _id: string;
  user_id: number;
  type: string;
  name: string;
  description: string;
  content: string;
  tags: string[];
  version: number;
  created_at: string;
  updated_at: string;
}

export interface EsMemoryVersion {
  _id: string;
  memory_id: string;
  user_id: number;
  version: number;
  type: string;
  name: string;
  description: string;
  content: string;
  tags: string[];
  created_at: string;
  updated_at: string;
  saved_at: string; // timestamp when this snapshot was created
}

async function esRequest<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${ES_URL}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`ES ${method} ${path} → ${res.status}: ${err}`);
  }
  return res.json();
}

export async function searchMemories(userId: number, query?: string): Promise<EsMemory[]> {
  // must_not is_current:false excludes archived versions while keeping docs that predate versioning
  const esQuery = query
    ? {
        bool: {
          must: [
            { term: { user_id: userId } },
            {
              multi_match: {
                query,
                fields: ["name", "description", "content", "tags"],
                fuzziness: "AUTO",
              },
            },
          ],
          must_not: [{ term: { is_current: false } }],
        },
      }
    : {
        bool: {
          must: [{ term: { user_id: userId } }],
          must_not: [{ term: { is_current: false } }],
        },
      };

  const result = await esRequest<{ hits: { hits: Array<{ _id: string; _source: Omit<EsMemory, "_id"> }> } }>(
    "POST",
    `/${MEMORIES_INDEX}/_search`,
    {
      query: esQuery,
      size: 10000,
      sort: [{ created_at: { order: "desc" } }],
    }
  );

  return result.hits.hits.map((h) => ({
    _id: h._id,
    ...h._source,
    version: h._source.version ?? 1, // backfill for existing docs without version
  }));
}

export async function getMemoryById(id: string): Promise<EsMemory | null> {
  try {
    const result = await esRequest<{ _id: string; found: boolean; _source: Omit<EsMemory, "_id"> }>(
      "GET",
      `/${MEMORIES_INDEX}/_doc/${id}`
    );
    if (!result.found) return null;
    return { _id: result._id, ...result._source, version: result._source.version ?? 1 };
  } catch {
    return null;
  }
}

export async function deleteMemory(id: string): Promise<void> {
  await esRequest("DELETE", `/${MEMORIES_INDEX}/_doc/${id}`);
}

export async function createMemory(
  userId: number,
  data: { type: string; name: string; description: string; content: string; tags?: string[] }
): Promise<string> {
  const now = new Date().toISOString();
  const result = await esRequest<{ _id: string }>("POST", `/${MEMORIES_INDEX}/_doc`, {
    user_id: userId,
    type: data.type,
    name: data.name,
    description: data.description,
    content: data.content,
    tags: data.tags ?? [],
    version: 1,
    created_at: now,
    updated_at: now,
  });
  return result._id;
}

export async function updateMemory(
  id: string,
  data: { type: string; name: string; description: string; content: string; tags?: string[] }
): Promise<void> {
  // 1. Fetch current doc to snapshot it
  const current = await getMemoryById(id);
  if (!current) throw new Error("Memory nicht gefunden.");

  const currentVersion = current.version ?? 1;

  // 2. Save snapshot of current state into history index
  await esRequest("POST", `/${HISTORY_INDEX}/_doc`, {
    memory_id: id,
    user_id: current.user_id,
    version: currentVersion,
    type: current.type,
    name: current.name,
    description: current.description,
    content: current.content,
    tags: current.tags,
    created_at: current.created_at,
    updated_at: current.updated_at,
    saved_at: new Date().toISOString(),
  });

  // 3. Apply update with incremented version
  await esRequest("POST", `/${MEMORIES_INDEX}/_update/${id}`, {
    doc: {
      type: data.type,
      name: data.name,
      description: data.description,
      content: data.content,
      tags: data.tags ?? [],
      version: currentVersion + 1,
      updated_at: new Date().toISOString(),
    },
  });
}

export async function getMemoryHistory(memoryId: string, userId: number): Promise<EsMemoryVersion[]> {
  try {
    const result = await esRequest<{
      hits: { hits: Array<{ _id: string; _source: Omit<EsMemoryVersion, "_id"> }> };
    }>(
      "POST",
      `/${HISTORY_INDEX}/_search`,
      {
        query: {
          bool: {
            must: [
              { term: { memory_id: memoryId } },
              { term: { user_id: userId } },
            ],
          },
        },
        size: 50,
        sort: [{ version: { order: "desc" } }],
      }
    );
    return result.hits.hits.map((h) => ({ _id: h._id, ...h._source }));
  } catch {
    // Index may not exist yet — return empty list gracefully
    return [];
  }
}

export async function getGraphSchema(userId: number): Promise<EsMemory | null> {
  try {
    const result = await esRequest<{
      hits: { hits: Array<{ _id: string; _source: Omit<EsMemory, "_id"> }> };
    }>("POST", `/${MEMORIES_INDEX}/_search`, {
      query: {
        bool: {
          must: [
            { term: { user_id: userId } },
            { term: { name: "_graph_schema" } },
            { term: { type: "schema" } },
          ],
        },
      },
      size: 1,
    });
    if (!result.hits.hits.length) return null;
    const h = result.hits.hits[0];
    return { _id: h._id, ...h._source, version: h._source.version ?? 1 };
  } catch {
    return null;
  }
}

export async function restoreMemoryVersion(id: string, version: number, userId: number): Promise<void> {
  // Find the snapshot for the requested version
  const result = await esRequest<{
    hits: { hits: Array<{ _id: string; _source: Omit<EsMemoryVersion, "_id"> }> };
  }>(
    "POST",
    `/${HISTORY_INDEX}/_search`,
    {
      query: {
        bool: {
          must: [
            { term: { memory_id: id } },
            { term: { user_id: userId } },
            { term: { version } },
          ],
        },
      },
      size: 1,
    }
  );

  if (!result.hits.hits.length) throw new Error("Version nicht gefunden.");
  const snap = result.hits.hits[0]._source;

  // Snapshot the current state before overwriting
  const current = await getMemoryById(id);
  if (!current) throw new Error("Memory nicht gefunden.");
  const currentVersion = current.version ?? 1;

  await esRequest("POST", `/${HISTORY_INDEX}/_doc`, {
    memory_id: id,
    user_id: current.user_id,
    version: currentVersion,
    type: current.type,
    name: current.name,
    description: current.description,
    content: current.content,
    tags: current.tags,
    created_at: current.created_at,
    updated_at: current.updated_at,
    saved_at: new Date().toISOString(),
  });

  // Write the restored content as a new version
  await esRequest("POST", `/${MEMORIES_INDEX}/_update/${id}`, {
    doc: {
      type: snap.type,
      name: snap.name,
      description: snap.description,
      content: snap.content,
      tags: snap.tags,
      version: currentVersion + 1,
      updated_at: new Date().toISOString(),
    },
  });
}
