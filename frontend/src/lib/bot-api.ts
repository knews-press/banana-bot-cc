import { getInstanceUrl } from "./instances";

export class BotApiClient {
  private baseUrl: string;
  private apiKey: string;

  constructor(instance: string, apiKey: string) {
    this.baseUrl = getInstanceUrl(instance);
    this.apiKey = apiKey;
  }

  private headers(): HeadersInit {
    return {
      Authorization: `Bearer ${this.apiKey}`,
      "Content-Type": "application/json",
    };
  }

  async chat(body: {
    message: string;
    session_id?: string | null;
    mode?: string;
    cwd?: string | null;
    stream?: boolean;
  }): Promise<Response> {
    return fetch(`${this.baseUrl}/api/v1/chat`, {
      method: "POST",
      headers: this.headers(),
      body: JSON.stringify(body),
    });
  }

  async getSessions(): Promise<Response> {
    return fetch(`${this.baseUrl}/api/v1/sessions`, {
      headers: this.headers(),
    });
  }

  async getSession(id: string): Promise<Response> {
    return fetch(`${this.baseUrl}/api/v1/sessions/${id}`, {
      headers: this.headers(),
    });
  }

  async deleteSession(id: string): Promise<Response> {
    return fetch(`${this.baseUrl}/api/v1/sessions/${id}`, {
      method: "DELETE",
      headers: this.headers(),
    });
  }

  async compactSession(id: string): Promise<Response> {
    return fetch(`${this.baseUrl}/api/v1/sessions/${id}/compact`, {
      method: "POST",
      headers: this.headers(),
    });
  }

  async getStatus(): Promise<Response> {
    return fetch(`${this.baseUrl}/api/v1/status`, {
      headers: this.headers(),
    });
  }

  async getStats(): Promise<Response> {
    return fetch(`${this.baseUrl}/api/v1/stats`, {
      headers: this.headers(),
    });
  }

  async streamSession(sessionId: string, signal?: AbortSignal): Promise<Response> {
    return fetch(`${this.baseUrl}/api/v1/sessions/${sessionId}/stream`, {
      headers: { Authorization: `Bearer ${this.apiKey}` }, // no Content-Type for SSE GET
      signal,
    });
  }

  async getLockStatus(sessionId: string): Promise<Response> {
    return fetch(`${this.baseUrl}/api/v1/sessions/${sessionId}/lock`, {
      headers: this.headers(),
    });
  }

  async getActiveLock(): Promise<Response> {
    return fetch(`${this.baseUrl}/api/v1/sessions/active-lock`, {
      headers: this.headers(),
    });
  }

  async stopSession(sessionId: string): Promise<Response> {
    return fetch(`${this.baseUrl}/api/v1/sessions/${sessionId}/stop`, {
      method: "POST",
      headers: this.headers(),
    });
  }

  async healthz(): Promise<boolean> {
    try {
      const res = await fetch(`${this.baseUrl}/healthz`, {
        signal: AbortSignal.timeout(3000),
      });
      return res.ok;
    } catch {
      return false;
    }
  }

  async getClusterStatus(): Promise<Response> {
    return fetch(`${this.baseUrl}/api/v1/cluster/status`, {
      headers: this.headers(),
    });
  }

  async getUploads(): Promise<Response> {
    return fetch(`${this.baseUrl}/api/v1/files/uploads`, {
      headers: this.headers(),
    });
  }

  async uploadFile(formData: FormData): Promise<Response> {
    // Don't include Content-Type — browser sets it with multipart boundary
    return fetch(`${this.baseUrl}/api/v1/files/upload`, {
      method: "POST",
      headers: { Authorization: `Bearer ${this.apiKey}` },
      body: formData,
    });
  }

  async getWorkspace(path: string = ""): Promise<Response> {
    const q = path ? `?path=${encodeURIComponent(path)}` : "";
    return fetch(`${this.baseUrl}/api/v1/files/workspace${q}`, {
      headers: this.headers(),
    });
  }

  async readFile(path: string): Promise<Response> {
    return fetch(`${this.baseUrl}/api/v1/files/read?path=${encodeURIComponent(path)}`, {
      headers: this.headers(),
    });
  }

  async downloadFile(path: string, workspace = false, inline = false): Promise<Response> {
    const params = new URLSearchParams({ path });
    if (workspace) params.set("workspace", "true");
    if (inline) params.set("inline", "true");
    return fetch(`${this.baseUrl}/api/v1/files/download?${params}`, {
      headers: this.headers(),
    });
  }

  async downloadUpload(uploadId: string): Promise<Response> {
    return fetch(`${this.baseUrl}/api/v1/files/upload-download?upload_id=${encodeURIComponent(uploadId)}`, {
      headers: this.headers(),
    });
  }

  async listCreations(): Promise<Response> {
    return fetch(`${this.baseUrl}/api/v1/files/creations`, {
      headers: this.headers(),
    });
  }

  async getJobs(): Promise<Response> {
    return fetch(`${this.baseUrl}/api/v1/jobs`, {
      headers: this.headers(),
    });
  }

  async getCommands(): Promise<Response> {
    return fetch(`${this.baseUrl}/api/v1/commands`, {
      headers: this.headers(),
    });
  }

  async executeCommand(command: string, args: string[]): Promise<Response> {
    return fetch(`${this.baseUrl}/api/v1/commands`, {
      method: "POST",
      headers: this.headers(),
      body: JSON.stringify({ command, args }),
    });
  }

  async getGraphSearch(params: {
    domain?: string;
    types?: string[];
    q?: string;
    limit?: number;
  }): Promise<Response> {
    const sp = new URLSearchParams();
    if (params.domain) sp.set("domain", params.domain);
    if (params.types?.length) sp.set("types", params.types.join(","));
    if (params.q) sp.set("q", params.q);
    if (params.limit) sp.set("limit", String(params.limit));
    const qs = sp.toString() ? `?${sp}` : "";
    return fetch(`${this.baseUrl}/api/v1/graph/search${qs}`, {
      headers: this.headers(),
    });
  }

  async getGraphNode(elementId: string): Promise<Response> {
    return fetch(
      `${this.baseUrl}/api/v1/graph/node/${encodeURIComponent(elementId)}`,
      { headers: this.headers() }
    );
  }

  async ingestMemory(body: {
    name: string;
    memory_type?: string;
    description?: string;
    content: string;
    tags?: string[];
  }): Promise<Response> {
    return fetch(`${this.baseUrl}/api/v1/memories`, {
      method: "POST",
      headers: this.headers(),
      body: JSON.stringify(body),
    });
  }
}
