"use client";

import { useParams, useSearchParams, useRouter } from "next/navigation";
import { useState, useEffect, Suspense } from "react";
import { useMemories } from "@/hooks/use-memories";
import type { EsMemory, EsMemoryVersion } from "@/hooks/use-memories";
import { Spinner } from "@/components/ui/spinner";
import { GraphTab } from "@/components/graph/graph-tab";

// ── Type config ────────────────────────────────────────────────────────────
const TYPE_CONFIG: Record<string, { label: string; accent: string }> = {
  user:        { label: "User",        accent: "#3b82f6" },
  project:     { label: "Project",     accent: "#8b5cf6" },
  decision:    { label: "Decision",    accent: "#f59e0b" },
  convention:  { label: "Convention",  accent: "#10b981" },
  reference:   { label: "Reference",   accent: "#6b7280" },
  credential:  { label: "Credential",   accent: "#ef4444" },
  todo:        { label: "Todo",         accent: "#f97316" },
  feedback:    { label: "Feedback",     accent: "#ec4899" },
  article:     { label: "Article",      accent: "#0ea5e9" },
  dossier:     { label: "Dossier",      accent: "#7c3aed" },
  thought:     { label: "Thought",      accent: "#a855f7" },
  excerpt:     { label: "Excerpt",      accent: "#14b8a6" },
  skill:       { label: "Skill",        accent: "#06b6d4" },
  draft:       { label: "Draft",        accent: "#84cc16" },
  schema:      { label: "Schema",       accent: "#d946ef" },
};
function typeCfg(type: string) {
  return TYPE_CONFIG[type] ?? { label: type, accent: "#6b7280" };
}
function useTypeOptions(memories: EsMemory[]): string[] {
  const fromMemories = new Set(memories.map((m) => m.type));
  for (const key of Object.keys(TYPE_CONFIG)) fromMemories.add(key);
  const knownOrder = Object.keys(TYPE_CONFIG);
  return [...fromMemories].sort((a, b) => {
    const ai = knownOrder.indexOf(a);
    const bi = knownOrder.indexOf(b);
    if (ai !== -1 && bi !== -1) return ai - bi;
    if (ai !== -1) return -1;
    if (bi !== -1) return 1;
    return a.localeCompare(b);
  });
}

// ── Shared input styles ───────────────────────────────────────────────────────
const inputClass = "w-full rounded-md px-3 py-2 text-[13px] focus:outline-none transition-colors";
const inputStyle: React.CSSProperties = {
  border: "1px solid var(--border)",
  backgroundColor: "var(--bg-elevated)",
  color: "var(--text)",
};

// ── Date helpers ──────────────────────────────────────────────────────────────
function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("de-DE", {
    day: "2-digit", month: "2-digit", year: "2-digit", timeZone: "Europe/Berlin",
  });
}
function fmtDateTime(iso: string): string {
  return new Date(iso).toLocaleString("de-DE", {
    day: "2-digit", month: "2-digit", year: "2-digit",
    hour: "2-digit", minute: "2-digit", timeZone: "Europe/Berlin",
  });
}

// ── Version history panel ─────────────────────────────────────────────────────
function VersionHistory({
  memoryId, currentVersion, instance, onRestore, onClose,
}: {
  memoryId: string; currentVersion: number; instance: string;
  onRestore: (version: number) => Promise<void>; onClose: () => void;
}) {
  const [history, setHistory] = useState<EsMemoryVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [restoring, setRestoring] = useState<number | null>(null);

  useEffect(() => {
    fetch(`/api/${instance}/memories/${memoryId}/history`)
      .then((r) => r.json())
      .then((data) => setHistory(Array.isArray(data) ? data : []))
      .catch(() => setHistory([]))
      .finally(() => setLoading(false));
  }, [memoryId, instance]);

  const handleRestore = async (version: number) => {
    setRestoring(version);
    try {
      await onRestore(version);
      onClose();
    } finally {
      setRestoring(null);
    }
  };

  return (
    <div className="mt-3 rounded-md overflow-hidden"
      style={{ border: "1px solid var(--border)", backgroundColor: "var(--bg-elevated)" }}>
      <div className="flex items-center justify-between px-3 py-2"
        style={{ borderBottom: "1px solid var(--border)", backgroundColor: "var(--bg-muted)" }}>
        <span className="text-[11px] font-medium uppercase tracking-wide" style={{ color: "var(--text-3)" }}>
          Version history
        </span>
        <button onClick={onClose} className="text-[12px]" style={{ color: "var(--text-3)" }}>✕</button>
      </div>
      {loading ? (
        <div className="flex justify-center py-4"><Spinner /></div>
      ) : history.length === 0 ? (
        <p className="text-[12px] px-3 py-3 text-center" style={{ color: "var(--text-3)" }}>
          No previous versions.
        </p>
      ) : (
        <div>
          <div className="flex items-center gap-3 px-3 py-2.5 text-[12px]"
            style={{ borderBottom: "1px solid var(--border)" }}>
            <span className="font-mono tabular-nums w-6 text-center" style={{ color: "var(--text-3)" }}>
              v{currentVersion}
            </span>
            <span style={{ color: "var(--text-2)" }}>Current version</span>
            <span className="ml-auto text-[10px] px-1.5 py-0.5 rounded font-mono"
              style={{ backgroundColor: "var(--accent)22", color: "var(--accent)" }}>
              aktuell
            </span>
          </div>
          {history.map((v) => (
            <div key={v._id} className="flex items-center gap-3 px-3 py-2.5 text-[12px]"
              style={{ borderBottom: "1px solid var(--border)" }}>
              <span className="font-mono tabular-nums w-6 text-center flex-shrink-0" style={{ color: "var(--text-3)" }}>
                v{v.version}
              </span>
              <span className="flex-shrink-0" style={{ color: "var(--text-2)" }}>{fmtDateTime(v.saved_at)}</span>
              <span className="truncate flex-1 text-[11px]" style={{ color: "var(--text-3)" }}>
                {v.content.slice(0, 50)}…
              </span>
              <button
                onClick={() => handleRestore(v.version)}
                disabled={restoring !== null}
                className="flex-shrink-0 text-[11px] px-2 py-1 rounded transition-colors disabled:opacity-40"
                style={{ color: "var(--text-2)", backgroundColor: "var(--bg-muted)", border: "1px solid var(--border)" }}
              >
                {restoring === v.version ? <Spinner className="h-3 w-3" /> : "Wiederherstellen"}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Inline edit form ──────────────────────────────────────────────────────────
function EditForm({
  memory, instance, onSave, onCancel, onRestoreVersion, typeOptions,
}: {
  memory: EsMemory; instance: string;
  onSave: (data: { type: string; name: string; description: string; content: string; tags: string[] }) => Promise<void>;
  onCancel: () => void;
  onRestoreVersion: (version: number) => Promise<void>;
  typeOptions: string[];
}) {
  const [type, setType] = useState(memory.type);
  const [name, setName] = useState(memory.name);
  const [description, setDescription] = useState(memory.description);
  const [content, setContent] = useState(memory.content);
  const [tags, setTags] = useState(memory.tags.join(", "));
  const [saving, setSaving] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const version = memory.version ?? 1;

  const handleSave = async () => {
    if (!name || !content) return;
    setSaving(true);
    try {
      await onSave({ type, name, description, content, tags: tags.split(",").map((t) => t.trim()).filter(Boolean) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="px-1 py-4 space-y-3"
      style={{ borderTop: "1px solid var(--border)", backgroundColor: "var(--bg-elevated)" }}>
      <div className="grid grid-cols-1 sm:grid-cols-[140px_1fr] gap-3">
        <div className="relative">
          <input list="edit-type-options" value={type} onChange={(e) => setType(e.target.value)}
            placeholder="Typ" className={inputClass} style={inputStyle} />
          <datalist id="edit-type-options">
            {typeOptions.map((t) => <option key={t} value={t}>{typeCfg(t).label}</option>)}
          </datalist>
        </div>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name *"
          className={inputClass} style={inputStyle} />
      </div>
      <input value={description} onChange={(e) => setDescription(e.target.value)}
        placeholder="Kurzbeschreibung (optional)" className={inputClass} style={inputStyle} />
      <textarea value={content} onChange={(e) => setContent(e.target.value)} placeholder="Inhalt *" rows={5}
        className={`${inputClass} resize-none font-mono text-[12px]`} style={inputStyle} />
      <input value={tags} onChange={(e) => setTags(e.target.value)}
        placeholder="Tags, kommagetrennt" className={inputClass} style={inputStyle} />
      <div className="flex items-center gap-2 flex-wrap">
        <button onClick={handleSave} disabled={saving || !name || !content}
          className="px-3 py-1.5 rounded-md text-[13px] font-medium transition-colors disabled:opacity-40 flex items-center gap-2"
          style={{ backgroundColor: "var(--text)", color: "var(--bg)" }}>
          {saving && <Spinner className="h-3.5 w-3.5" />}
          Save
        </button>
        <button onClick={onCancel} className="px-3 py-1.5 rounded-md text-[13px] transition-colors"
          style={{ color: "var(--text-2)", backgroundColor: "var(--bg-muted)" }}>
          Abbrechen
        </button>
        {version > 1 && (
          <button onClick={() => setShowHistory((v) => !v)}
            className="ml-auto text-[12px] flex items-center gap-1 transition-colors"
            style={{ color: showHistory ? "var(--accent)" : "var(--text-3)" }}>
            <span>◷</span>
            <span>v{version} · {version - 1} earlier version{version - 1 !== 1 ? "s" : ""}</span>
            <span style={{ fontSize: 9 }}>{showHistory ? "▲" : "▼"}</span>
          </button>
        )}
        {version === 1 && (
          <span className="ml-auto text-[11px]" style={{ color: "var(--text-3)" }}>v1 · keine früheren Versionen</span>
        )}
      </div>
      {showHistory && (
        <VersionHistory
          memoryId={memory._id}
          currentVersion={version}
          instance={instance}
          onRestore={onRestoreVersion}
          onClose={() => setShowHistory(false)}
        />
      )}
    </div>
  );
}

// ── New memory form ───────────────────────────────────────────────────────────
function NewMemoryForm({ onCreate, onCancel, typeOptions }: {
  onCreate: (data: { type: string; name: string; description: string; content: string; tags: string[] }) => Promise<void>;
  onCancel: () => void;
  typeOptions: string[];
}) {
  const [type, setType] = useState("user");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [content, setContent] = useState("");
  const [tags, setTags] = useState("");
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    if (!name || !content) return;
    setSaving(true);
    try {
      await onCreate({ type, name, description, content, tags: tags.split(",").map((t) => t.trim()).filter(Boolean) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3 pb-6" style={{ borderBottom: "1px solid var(--border)" }}>
      <p className="text-[11px] font-medium uppercase tracking-wide" style={{ color: "var(--text-3)" }}>
        Neues Memory
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-[140px_1fr] gap-3">
        <div className="relative">
          <input list="new-type-options" value={type} onChange={(e) => setType(e.target.value)}
            placeholder="Typ" className={inputClass} style={inputStyle} />
          <datalist id="new-type-options">
            {typeOptions.map((t) => <option key={t} value={t}>{typeCfg(t).label}</option>)}
          </datalist>
        </div>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name *"
          className={inputClass} style={inputStyle} />
      </div>
      <input value={description} onChange={(e) => setDescription(e.target.value)}
        placeholder="Kurzbeschreibung (optional)" className={inputClass} style={inputStyle} />
      <textarea value={content} onChange={(e) => setContent(e.target.value)} placeholder="Inhalt *" rows={4}
        className={`${inputClass} resize-none font-mono text-[12px]`} style={inputStyle} />
      <input value={tags} onChange={(e) => setTags(e.target.value)}
        placeholder="Tags, kommagetrennt" className={inputClass} style={inputStyle} />
      <div className="flex items-center gap-2">
        <button onClick={handleSave} disabled={saving || !name || !content}
          className="px-3 py-1.5 rounded-md text-[13px] font-medium transition-colors disabled:opacity-40 flex items-center gap-2"
          style={{ backgroundColor: "var(--text)", color: "var(--bg)" }}>
          {saving && <Spinner className="h-3.5 w-3.5" />}
          Save
        </button>
        <button onClick={onCancel} className="px-3 py-1.5 rounded-md text-[13px] transition-colors"
          style={{ color: "var(--text-2)", backgroundColor: "var(--bg-muted)" }}>
          Abbrechen
        </button>
      </div>
    </div>
  );
}

// ── Memory content display ────────────────────────────────────────────────────
function MemoryContent({ content, type }: { content: string; type: string }) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let parsed: any = null;
  try {
    const trimmed = content.trim();
    if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
      parsed = JSON.parse(trimmed);
    }
  } catch { /* not JSON */ }

  if (!parsed) {
    return (
      <pre className="text-[12px] whitespace-pre-wrap leading-relaxed pt-3 font-sans"
        style={{ color: "var(--text-2)" }}>
        {content}
      </pre>
    );
  }

  const p = parsed as Record<string, unknown>;
  const isOntology = !!(type === "schema" && p.nodes && p.edges);
  const nodeCount = isOntology ? Object.keys(p.nodes as object).length : 0;
  const edgeCount = isOntology ? (Array.isArray(p.edges) ? (p.edges as unknown[]).length : 0) : 0;
  const embeddingNodes = isOntology
    ? Object.entries(p.nodes as Record<string, { embedding?: boolean }>)
        .filter(([, c]) => c.embedding)
        .map(([k]) => k)
    : [];

  return (
    <div className="pt-3 space-y-2">
      {isOntology && (
        <div className="flex flex-wrap gap-3 text-[11px] mb-2" style={{ color: "var(--text-3)" }}>
          <span className="px-2 py-0.5 rounded" style={{ backgroundColor: "var(--bg-muted)", border: "1px solid var(--border)" }}>
            {nodeCount} Node-Typen
          </span>
          <span className="px-2 py-0.5 rounded" style={{ backgroundColor: "var(--bg-muted)", border: "1px solid var(--border)" }}>
            {edgeCount} Edge-Typen
          </span>
          <span className="px-2 py-0.5 rounded" style={{ backgroundColor: "var(--bg-muted)", border: "1px solid var(--border)" }}>
            {embeddingNodes.length} Vektor-Indizes
          </span>
        </div>
      )}
      <pre className="text-[11px] leading-relaxed font-mono overflow-x-auto rounded-md p-3"
        style={{ color: "var(--text-2)", backgroundColor: "var(--bg-muted)", border: "1px solid var(--border)" }}>
        {JSON.stringify(parsed, null, 2)}
      </pre>
    </div>
  );
}

// ── Memory row ────────────────────────────────────────────────────────────────
function MemoryRow({ memory, instance, onDelete, onUpdate, onRestore, typeOptions }: {
  memory: EsMemory; instance: string;
  onDelete: () => void;
  onUpdate: (data: { type: string; name: string; description: string; content: string; tags: string[] }) => Promise<void>;
  onRestore: (version: number) => Promise<void>;
  typeOptions: string[];
}) {
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const cfg = typeCfg(memory.type);

  const handleUpdate = async (data: Parameters<typeof onUpdate>[0]) => {
    await onUpdate(data);
    setEditing(false);
  };

  return (
    <div style={{ borderTop: "1px solid var(--border)" }}>
      <div className="flex items-start gap-3 py-2.5 px-1 text-[13px]">
        <span className="w-1.5 h-1.5 rounded-full flex-shrink-0 mt-[6px]" style={{ backgroundColor: cfg.accent }} />
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2 flex-wrap min-w-0">
            <span className="text-[11px] font-semibold uppercase tracking-wider flex-shrink-0"
              style={{ color: cfg.accent }}>
              {cfg.label}
            </span>
            <span className="font-medium truncate" style={{ color: "var(--text)" }}>{memory.name}</span>
            {memory.description && (
              <span className="text-[12px] truncate hidden sm:inline" style={{ color: "var(--text-3)" }}>
                {memory.description}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0 ml-2">
          <span className="text-[11px] tabular-nums mr-1" style={{ color: "var(--text-3)" }}>
            {fmtDate(memory.updated_at || memory.created_at)}
          </span>
          <button onClick={() => { setEditing(!editing); setExpanded(false); setConfirming(false); }}
            className="p-2 rounded transition-colors" title="Bearbeiten"
            style={{ color: editing ? "var(--accent)" : "var(--text-3)" }}
            onMouseEnter={(e) => { if (!editing) (e.currentTarget as HTMLElement).style.color = "var(--text-2)"; }}
            onMouseLeave={(e) => { if (!editing) (e.currentTarget as HTMLElement).style.color = "var(--text-3)"; }}>
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5"
              strokeLinecap="round" strokeLinejoin="round">
              <path d="M8.5 1.5a1.414 1.414 0 012 2L3.5 10.5 1 11l.5-2.5L8.5 1.5z" />
            </svg>
          </button>
          <button onClick={() => { setExpanded(!expanded); setEditing(false); }}
            className="p-2 rounded text-[10px] transition-colors" title={expanded ? "Einklappen" : "Inhalt anzeigen"}
            style={{ color: "var(--text-3)" }}
            onMouseEnter={(e) => (e.currentTarget as HTMLElement).style.color = "var(--text-2)"}
            onMouseLeave={(e) => (e.currentTarget as HTMLElement).style.color = "var(--text-3)"}>
            {expanded ? "▲" : "▼"}
          </button>
          {confirming ? (
            <div className="flex items-center gap-1">
              <button onClick={() => { onDelete(); setConfirming(false); }}
                className="text-[11px] px-2 py-0.5 rounded"
                style={{ backgroundColor: "var(--danger)", color: "white" }}>
                Löschen
              </button>
              <button onClick={() => setConfirming(false)}
                className="text-[11px] px-2 py-0.5 rounded"
                style={{ color: "var(--text-2)", backgroundColor: "var(--bg-muted)" }}>
                Nein
              </button>
            </div>
          ) : (
            <button onClick={() => setConfirming(true)} className="p-2 rounded transition-colors" title="Löschen"
              style={{ color: "var(--text-3)" }}
              onMouseEnter={(e) => (e.currentTarget as HTMLElement).style.color = "var(--danger)"}
              onMouseLeave={(e) => (e.currentTarget as HTMLElement).style.color = "var(--text-3)"}>
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5"
                strokeLinecap="round" strokeLinejoin="round">
                <path d="M1 3h10M4 3V2a1 1 0 011-1h2a1 1 0 011 1v1M5 5.5v3M7 5.5v3M2 3l.7 6.5a1 1 0 001 .9h4.6a1 1 0 001-.9L10 3" />
              </svg>
            </button>
          )}
        </div>
      </div>

      {expanded && !editing && (
        <div className="pb-3 px-1 pl-5"
          style={{ borderTop: "1px solid var(--border)", backgroundColor: "var(--bg-elevated)" }}>
          <MemoryContent content={memory.content} type={memory.type} />
          {memory.tags?.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {memory.tags.map((tag) => (
                <span key={tag} className="text-[10px] px-1.5 py-0.5 rounded"
                  style={{ backgroundColor: "var(--bg-muted)", color: "var(--text-3)", border: "1px solid var(--border)" }}>
                  {tag}
                </span>
              ))}
            </div>
          )}
          <p className="text-[11px] mt-2.5" style={{ color: "var(--text-3)" }}>
            Erstellt {fmtDateTime(memory.created_at)}
            {(memory.version ?? 1) > 1 && ` · v${memory.version}`}
          </p>
        </div>
      )}

      {editing && (
        <EditForm
          key={memory._id}
          memory={memory}
          instance={instance}
          onSave={handleUpdate}
          onCancel={() => setEditing(false)}
          onRestoreVersion={onRestore}
          typeOptions={typeOptions}
        />
      )}
    </div>
  );
}

// ── Memories list (existing tab content) ─────────────────────────────────────
function MemoriesListTab({ instance }: { instance: string }) {
  const { memories, isLoading, error, query, search, remove, create, update, restore } = useMemories(instance);
  const [showForm, setShowForm] = useState(false);
  const typeOptions = useTypeOptions(memories);

  const grouped = memories.reduce<Record<string, EsMemory[]>>((acc, m) => {
    (acc[m.type] ??= []).push(m);
    return acc;
  }, {});

  const typeOrder = ["schema", "user", "project", "decision", "convention", "reference", "credential", "todo", "feedback"];
  const sortedTypes = [
    ...typeOrder.filter((t) => grouped[t]),
    ...Object.keys(grouped).filter((t) => !typeOrder.includes(t)),
  ];

  return (
    <div className="flex-1 overflow-y-auto px-4 py-5 md:p-8" style={{ backgroundColor: "var(--bg)" }}>
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-[18px] font-semibold tracking-tight" style={{ color: "var(--text)" }}>Memories</h1>
            <p className="text-[12px] mt-0.5" style={{ color: "var(--text-3)" }}>
              {memories.length} Eintrag{memories.length !== 1 ? "e" : ""}
              {query && ` · Suche: „${query}"`}
            </p>
          </div>
          <button
            onClick={() => setShowForm(!showForm)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[13px] font-medium transition-colors"
            style={showForm
              ? { backgroundColor: "var(--bg-muted)", color: "var(--text-2)", border: "1px solid var(--border)" }
              : { backgroundColor: "var(--text)", color: "var(--bg)" }
            }
          >
            <svg width="11" height="11" viewBox="0 0 11 11" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              {showForm
                ? <><line x1="1" y1="1" x2="10" y2="10" /><line x1="10" y1="1" x2="1" y2="10" /></>
                : <><line x1="5.5" y1="1" x2="5.5" y2="10" /><line x1="1" y1="5.5" x2="10" y2="5.5" /></>}
            </svg>
            {showForm ? "Abbrechen" : "Neu"}
          </button>
        </div>

        {showForm && (
          <div className="mb-6">
            <NewMemoryForm
              onCreate={async (data) => { await create(data); setShowForm(false); }}
              onCancel={() => setShowForm(false)}
              typeOptions={typeOptions}
            />
          </div>
        )}

        {/* Search */}
        <div className="relative mb-6">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none"
            style={{ color: "var(--text-3)" }}
            width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round">
            <circle cx="5.5" cy="5.5" r="4" /><line x1="8.75" y1="8.75" x2="12" y2="12" />
          </svg>
          <input type="search" placeholder="Memories durchsuchen…" value={query}
            onChange={(e) => search(e.target.value)}
            className="w-full pl-8 pr-4 py-2 rounded-md text-[13px] focus:outline-none"
            style={{ border: "1px solid var(--border)", backgroundColor: "var(--bg-elevated)", color: "var(--text)" }}
          />
        </div>

        {/* List */}
        {isLoading ? (
          <div className="flex justify-center py-16"><Spinner /></div>
        ) : error ? (
          <div className="text-center py-8 text-[13px]" style={{ color: "var(--danger)" }}>{error}</div>
        ) : memories.length === 0 ? (
          <div className="text-center py-16 text-[13px]" style={{ color: "var(--text-3)" }}>
            {query ? `Keine Ergebnisse für „${query}".` : "Noch keine Memories gespeichert."}
          </div>
        ) : (
          <div className="space-y-8">
            {sortedTypes.map((type) => (
              <section key={type}>
                <h3 className="text-[13px] font-medium mb-3" style={{ color: "var(--text-2)" }}>
                  {typeCfg(type).label}
                  <span className="ml-1.5 font-normal" style={{ color: "var(--text-3)" }}>
                    ({grouped[type].length})
                  </span>
                </h3>
                <div style={{ borderTop: "1px solid var(--border)" }}>
                  {grouped[type].map((m) => (
                    <MemoryRow
                      key={m._id}
                      memory={m}
                      instance={instance}
                      onDelete={() => remove(m._id)}
                      onUpdate={(data) => update(m._id, data)}
                      onRestore={(version) => restore(m._id, version)}
                      typeOptions={typeOptions}
                    />
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Tab types ─────────────────────────────────────────────────────────────────
type Tab = "memories" | "graph";

const TABS: { id: Tab; label: string }[] = [
  { id: "memories", label: "Memories" },
  { id: "graph",    label: "Graph" },
];

// ── Inner page (needs useSearchParams → must be inside Suspense) ──────────────
function MemoriesPageInner() {
  const { instance } = useParams<{ instance: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();

  const tab = (searchParams.get("tab") as Tab) ?? "memories";
  const setTab = (t: Tab) => router.replace(`/${instance}/memories?tab=${t}`);

  return (
    <div className="flex-1 flex flex-col overflow-hidden" style={{ backgroundColor: "var(--bg)" }}>
      {/* Tab bar */}
      <div className="flex-shrink-0 px-4 md:px-8"
        style={{ borderBottom: "1px solid var(--border)" }}>
        <div className="flex gap-0 max-w-2xl" style={{ marginLeft: 0 }}>
          {TABS.map(({ id, label }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className="px-4 py-3 text-[13px] font-medium transition-colors border-b-2 -mb-px"
              style={{
                borderColor: tab === id ? "var(--accent)" : "transparent",
                color: tab === id ? "var(--accent)" : "var(--text-3)",
              }}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      {tab === "memories" && <MemoriesListTab instance={instance} />}
      {tab === "graph"    && <GraphTab instance={instance} />}
    </div>
  );
}

// ── Page export ───────────────────────────────────────────────────────────────
export default function MemoriesPage() {
  return (
    <Suspense fallback={
      <div className="flex-1 flex justify-center items-center" style={{ backgroundColor: "var(--bg)" }}>
        <Spinner />
      </div>
    }>
      <MemoriesPageInner />
    </Suspense>
  );
}
