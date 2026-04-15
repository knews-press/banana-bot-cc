"use client";

import { useParams, useSearchParams, useRouter } from "next/navigation";
import { useState, useEffect, useCallback, Suspense } from "react";
import dynamic from "next/dynamic";
import { Spinner } from "@/components/ui/spinner";

// Monaco loaded client-side only (no SSR)
const MonacoEditor = dynamic(() => import("@monaco-editor/react"), { ssr: false });

// ── Types ─────────────────────────────────────────────────────────────────────

type RenderType = "code" | "markdown" | "image" | "audio" | "video" | "csv" | "pdf" | "binary";

interface Upload {
  upload_id: string;
  filename: string;
  media_type: string | null;
  mime_type: string | null;
  file_size: number;
  storage_path: string | null;
  created_at: string | null;
  caption: string | null;
  indexed_es: boolean;
  indexed_mysql: boolean;
  enriched_memory: string | null;
  exists_on_disk: boolean;
}

interface WorkspaceEntry {
  name: string;
  path: string;
  is_dir: boolean;
  size: number | null;
  modified: number | null;
}

interface WorkspaceListing {
  path: string;
  entries: WorkspaceEntry[];
}

interface FileContent {
  path: string;
  name: string;
  content: string;
  size: number;
  mime_type: string | null;
  language: string | null;
  render_type: RenderType;
  previewable: boolean;
}

interface CreationFile {
  filename: string;
  path: string;
  size: number;
  modified: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtBytes(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + " MB";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + " KB";
  return n + " B";
}

function fmtDate(s: string | null): string {
  if (!s) return "—";
  return new Date(s).toLocaleDateString("de-DE", {
    day: "2-digit", month: "2-digit", year: "numeric",
    timeZone: "Europe/Berlin",
  });
}

function fmtModified(ts: number | null): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleDateString("de-DE", {
    day: "2-digit", month: "2-digit", year: "numeric",
    timeZone: "Europe/Berlin",
  });
}

// ── Icons ─────────────────────────────────────────────────────────────────────

function FolderIcon({ open }: { open?: boolean }) {
  return open ? (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M1 4a1 1 0 011-1h3l1.5 2H12a1 1 0 011 1v5a1 1 0 01-1 1H2a1 1 0 01-1-1V4z" />
    </svg>
  ) : (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M1 4a1 1 0 011-1h3l1.5 2H12a1 1 0 011 1v5a1 1 0 01-1 1H2a1 1 0 01-1-1V4z" />
    </svg>
  );
}

function FileIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 1h5l3 3v8a1 1 0 01-1 1H3a1 1 0 01-1-1V2a1 1 0 011-1z" />
      <polyline points="8 1 8 4 11 4" />
    </svg>
  );
}

function ChevronIcon({ dir }: { dir: "right" | "down" }) {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"
      style={{ transform: dir === "down" ? "rotate(90deg)" : "none", transition: "transform 0.1s" }}>
      <polyline points="3 2 7 5 3 8" />
    </svg>
  );
}

function UploadIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 10v2a1 1 0 001 1h8a1 1 0 001-1v-2" />
      <polyline points="10 4 7 1 4 4" />
      <line x1="7" y1="1" x2="7" y2="9" />
    </svg>
  );
}

// ── Badge ─────────────────────────────────────────────────────────────────────

function Badge({ label, active, title }: { label: string; active: boolean; title?: string }) {
  return (
    <span
      title={title}
      className="inline-flex items-center px-1.5 py-px rounded text-[10px] font-medium font-mono"
      style={{
        backgroundColor: active ? "color-mix(in srgb, var(--accent) 15%, transparent)" : "var(--bg-muted)",
        color: active ? "var(--accent)" : "var(--text-3)",
        border: `1px solid ${active ? "color-mix(in srgb, var(--accent) 30%, transparent)" : "var(--border)"}`,
      }}
    >
      {label}
    </span>
  );
}

// ── Media type badge ──────────────────────────────────────────────────────────

const MEDIA_COLORS: Record<string, string> = {
  image: "#78716c", video: "#57534e", audio: "#a8a29e",
  pdf: "#dc2626", docx: "#2563eb", xlsx: "#16a34a",
  csv: "#16a34a", text: "#6b7280", voice: "#7c3aed",
};

function MediaBadge({ type }: { type: string | null }) {
  const color = type ? (MEDIA_COLORS[type] ?? "#6b7280") : "#6b7280";
  return (
    <span
      className="inline-flex items-center px-1.5 py-px rounded text-[10px] font-medium uppercase"
      style={{ backgroundColor: color + "22", color, border: `1px solid ${color}44` }}
    >
      {type ?? "?"}
    </span>
  );
}

// ── File icon helpers ──────────────────────────────────────────────────────────

const EXT_ICONS: Record<string, string> = {
  docx: "📄", xlsx: "📊", csv: "📋", pdf: "📕", txt: "📝", md: "📝",
  mp3: "🎵", wav: "🎵", ogg: "🎵", png: "🖼️", jpg: "🖼️", jpeg: "🖼️",
  gif: "🖼️", webp: "🖼️", svg: "🖼️", dxf: "📐", dwg: "📐",
  zip: "📦", tar: "📦", gz: "📦", mp4: "🎬", webm: "🎬",
};

function fileIcon(filename: string): string {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  return EXT_ICONS[ext] ?? "📎";
}

// ── Markdown renderer ─────────────────────────────────────────────────────────

function renderMarkdown(md: string): string {
  return md
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/^### (.+)$/gm, "<h3 style='font-size:14px;font-weight:600;margin:12px 0 4px'>$1</h3>")
    .replace(/^## (.+)$/gm, "<h2 style='font-size:16px;font-weight:600;margin:16px 0 6px'>$1</h2>")
    .replace(/^# (.+)$/gm, "<h1 style='font-size:20px;font-weight:700;margin:20px 0 8px'>$1</h1>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`(.+?)`/g, "<code style='font-family:monospace;font-size:11px;background:var(--bg-muted);padding:1px 4px;border-radius:3px'>$1</code>")
    .replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2" target="_blank" rel="noopener" style="color:var(--accent)">$1</a>')
    .replace(/^- (.+)$/gm, "<li style='margin:2px 0;padding-left:8px'>$1</li>")
    .replace(/\n\n/g, "</p><p style='margin:8px 0'>")
    .replace(/\n/g, "<br/>");
}

// ── CSV Preview ───────────────────────────────────────────────────────────────

function CsvPreview({ content }: { content: string }) {
  const lines = content.split("\n").filter(Boolean);
  const headers = lines[0]?.split(",").map(s => s.trim().replace(/^"|"$/g, "")) ?? [];
  const rows = lines.slice(1, 101).map(l => l.split(",").map(s => s.trim().replace(/^"|"$/g, "")));
  return (
    <div className="overflow-auto h-full p-4">
      {lines.length > 101 && (
        <p className="text-[11px] mb-2" style={{ color: "var(--text-3)" }}>Zeige erste 100 Zeilen</p>
      )}
      <table className="text-[12px] border-collapse w-full">
        <thead>
          <tr>
            {headers.map((h, i) => (
              <th key={i} className="text-left px-2 py-1.5 font-medium whitespace-nowrap"
                style={{ borderBottom: "2px solid var(--border)", color: "var(--text-2)", backgroundColor: "var(--bg-muted)" }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri}
              onMouseEnter={e => (e.currentTarget as HTMLElement).style.backgroundColor = "var(--bg-subtle)"}
              onMouseLeave={e => (e.currentTarget as HTMLElement).style.backgroundColor = ""}
            >
              {row.map((cell, ci) => (
                <td key={ci} className="px-2 py-1 whitespace-nowrap"
                  style={{ borderBottom: "1px solid var(--border)", color: "var(--text)" }}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── File Renderer ─────────────────────────────────────────────────────────────

function FileRenderer({ file, instance, monacoTheme }: {
  file: FileContent; instance: string; monacoTheme: string;
}) {
  const dlUrl = (p: string, ws: boolean) =>
    `/api/${instance}/files/download?path=${encodeURIComponent(p)}${ws ? "&workspace=true" : ""}`;
  // Workspace files have relative paths (no leading slash)
  const isWorkspace = !file.path.startsWith("/");

  if (file.render_type === "binary") {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 p-8">
        <span style={{ fontSize: 48 }}>{fileIcon(file.name)}</span>
        <p className="text-[14px] font-medium" style={{ color: "var(--text)" }}>{file.name}</p>
        <p className="text-[12px]" style={{ color: "var(--text-3)" }}>
          Diese Datei kann nicht als Text angezeigt werden.
        </p>
        <a
          href={dlUrl(file.path, isWorkspace)}
          download={file.name}
          className="px-4 py-2 rounded-md text-[13px] font-medium"
          style={{ backgroundColor: "var(--accent)", color: "white" }}
        >
          ↓ Herunterladen
        </a>
      </div>
    );
  }

  if (file.render_type === "image") {
    return (
      <div className="flex items-center justify-center p-4 min-h-full bg-[var(--bg-subtle)]">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={dlUrl(file.path, isWorkspace)}
          alt={file.name}
          className="max-w-full object-contain rounded shadow-sm"
          style={{ maxHeight: "70vh" }}
        />
      </div>
    );
  }

  if (file.render_type === "audio") {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 p-8">
        <span style={{ fontSize: 40 }}>🎵</span>
        <p className="text-[13px] font-medium" style={{ color: "var(--text)" }}>{file.name}</p>
        <audio controls src={dlUrl(file.path, isWorkspace)} className="w-full max-w-md" />
      </div>
    );
  }

  if (file.render_type === "video") {
    return (
      <div className="flex items-center justify-center p-4 min-h-full">
        <video controls src={dlUrl(file.path, isWorkspace)} className="max-w-full rounded" style={{ maxHeight: "70vh" }} />
      </div>
    );
  }

  if (file.render_type === "pdf") {
    return (
      <iframe
        src={dlUrl(file.path, isWorkspace)}
        className="w-full h-full"
        style={{ minHeight: "600px", border: "none" }}
        title={file.name}
      />
    );
  }

  if (file.render_type === "markdown") {
    return (
      <div
        className="overflow-auto h-full p-6 text-[13px] leading-relaxed"
        style={{ color: "var(--text)" }}
        dangerouslySetInnerHTML={{ __html: renderMarkdown(file.content) }}
      />
    );
  }

  if (file.render_type === "csv") {
    return <CsvPreview content={file.content} />;
  }

  // Default: Monaco
  return (
    <MonacoEditor
      height="100%"
      language={file.language ?? "plaintext"}
      value={file.content}
      theme={monacoTheme}
      options={{
        readOnly: true,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        fontSize: 12,
        lineHeight: 18,
        fontFamily: "'Geist Mono', 'JetBrains Mono', 'Fira Code', monospace",
        renderLineHighlight: "gutter",
        overviewRulerBorder: false,
        hideCursorInOverviewRuler: true,
        scrollbar: { verticalScrollbarSize: 6, horizontalScrollbarSize: 6 },
        padding: { top: 12, bottom: 12 },
        wordWrap: "on",
      }}
    />
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// UPLOADS TAB
// ══════════════════════════════════════════════════════════════════════════════

function UploadsTab({ instance }: { instance: string }) {
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const [uploadState, setUploadState] = useState<"idle" | "uploading" | "success" | "error">("idle");
  const [uploadMsg, setUploadMsg] = useState<string>("");

  const loadUploads = useCallback(() => {
    setIsLoading(true);
    fetch(`/api/${instance}/files/uploads`)
      .then((r) => r.json())
      .then((data) => {
        if (Array.isArray(data)) setUploads(data);
        else setError(data.error ?? "Failed to load.");
      })
      .catch(() => setError("Netzwerkfehler."))
      .finally(() => setIsLoading(false));
  }, [instance]);

  useEffect(() => { loadUploads(); }, [loadUploads]);

  const handleUpload = useCallback(async (files: FileList | File[]) => {
    const file = files[0];
    if (!file) return;
    setUploadState("uploading");
    setUploadMsg(`${file.name} wird hochgeladen…`);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(`/api/${instance}/files/upload`, { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) {
        setUploadState("error");
        setUploadMsg(data.detail ?? data.error ?? "Upload fehlgeschlagen.");
      } else {
        setUploadState("success");
        setUploadMsg(data.summary ?? `${file.name} hochgeladen.`);
        loadUploads();
        setTimeout(() => { setUploadState("idle"); setUploadMsg(""); }, 3000);
      }
    } catch {
      setUploadState("error");
      setUploadMsg("Netzwerkfehler beim Upload.");
    }
  }, [instance, loadUploads]);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files.length) handleUpload(e.dataTransfer.files);
  }, [handleUpload]);

  const filtered = uploads.filter((u) =>
    !search ||
    u.filename.toLowerCase().includes(search.toLowerCase()) ||
    (u.caption ?? "").toLowerCase().includes(search.toLowerCase())
  );

  if (isLoading) return <div className="flex justify-center py-16"><Spinner /></div>;
  if (error) return <p className="text-[13px] py-8 text-center" style={{ color: "var(--danger)" }}>{error}</p>;

  const inputStyle: React.CSSProperties = {
    border: "1px solid var(--border)",
    backgroundColor: "var(--bg-elevated)",
    color: "var(--text)",
  };

  const dropZoneBg = isDragging
    ? "color-mix(in srgb, var(--accent) 8%, var(--bg-elevated))"
    : "var(--bg-elevated)";
  const dropZoneBorder = isDragging ? "var(--accent)" : "var(--border)";

  return (
    <div>
      {/* Upload drop zone */}
      <div
        className="mb-5 rounded-lg px-4 py-5 flex flex-col items-center gap-2 cursor-pointer transition-colors"
        style={{
          border: `1.5px dashed ${dropZoneBorder}`,
          backgroundColor: dropZoneBg,
        }}
        onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={onDrop}
        onClick={() => {
          const input = document.createElement("input");
          input.type = "file";
          input.onchange = (e) => {
            const files = (e.target as HTMLInputElement).files;
            if (files) handleUpload(files);
          };
          input.click();
        }}
      >
        {uploadState === "uploading" ? (
          <>
            <Spinner className="h-4 w-4" />
            <p className="text-[12px]" style={{ color: "var(--text-2)" }}>{uploadMsg}</p>
          </>
        ) : uploadState === "success" ? (
          <>
            <span style={{ color: "var(--success, #16a34a)", fontSize: 18 }}>✓</span>
            <p className="text-[12px]" style={{ color: "var(--text-2)" }}>{uploadMsg}</p>
          </>
        ) : uploadState === "error" ? (
          <>
            <span style={{ color: "var(--danger)", fontSize: 18 }}>✕</span>
            <p className="text-[12px]" style={{ color: "var(--danger)" }}>{uploadMsg}</p>
          </>
        ) : (
          <>
            <UploadIcon />
            <p className="text-[12px]" style={{ color: "var(--text-3)" }}>
              Datei hier ablegen oder <span style={{ color: "var(--accent)" }}>klicken</span> zum Auswählen
            </p>
            <p className="text-[10px]" style={{ color: "var(--text-3)" }}>PDF, Bild, Video, Audio, DOCX, XLSX, CSV, Text · max. 500 MB</p>
          </>
        )}
      </div>

      {/* Summary */}
      <div className="flex items-center gap-4 mb-4">
        <p className="text-[12px]" style={{ color: "var(--text-3)" }}>
          {uploads.length} Datei{uploads.length !== 1 ? "en" : ""}
          {" · "}
          {uploads.filter((u) => u.indexed_es).length} in ES
          {" · "}
          {uploads.filter((u) => u.indexed_mysql).length} in SQL
          {" · "}
          {uploads.filter((u) => u.enriched_memory).length} im Graph
        </p>
      </div>

      {/* Search */}
      <input
        type="text"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Dateiname oder Caption suchen…"
        className="w-full rounded-md px-3 py-2 text-[13px] focus:outline-none transition-colors mb-4"
        style={inputStyle}
      />

      {filtered.length === 0 ? (
        <p className="text-[13px] py-8 text-center" style={{ color: "var(--text-3)" }}>
          {search ? "No results." : "No uploads found."}
        </p>
      ) : (
        <div>
          {/* ── Desktop table (md+) ── */}
          <div className="hidden md:block space-y-px">
            <div
              className="grid text-[10px] uppercase tracking-widest px-3 py-1.5 rounded-t-md"
              style={{
                gridTemplateColumns: "1fr 80px 120px 60px 80px 80px 80px 48px",
                color: "var(--text-3)",
                backgroundColor: "var(--bg-muted)",
                borderBottom: "1px solid var(--border)",
              }}
            >
              <span>Datei</span><span>Typ</span><span>Datum</span>
              <span className="text-right">Größe</span>
              <span className="text-center">ES</span>
              <span className="text-center">SQL</span>
              <span className="text-center">Graph</span>
              <span></span>
            </div>
            {filtered.map((u) => (
              <div
                key={u.upload_id}
                className="grid items-center px-3 py-2 transition-colors"
                style={{
                  gridTemplateColumns: "1fr 80px 120px 60px 80px 80px 80px 48px",
                  borderBottom: "1px solid var(--border)",
                  backgroundColor: "var(--bg)",
                }}
                onMouseEnter={(e) => (e.currentTarget as HTMLElement).style.backgroundColor = "var(--bg-elevated)"}
                onMouseLeave={(e) => (e.currentTarget as HTMLElement).style.backgroundColor = "var(--bg)"}
              >
                <div className="min-w-0">
                  <p className="text-[12px] truncate" style={{ color: "var(--text)" }} title={u.filename}>{u.filename}</p>
                  {u.caption && <p className="text-[11px] truncate mt-0.5" style={{ color: "var(--text-3)" }}>{u.caption}</p>}
                </div>
                <span><MediaBadge type={u.media_type} /></span>
                <span className="text-[11px]" style={{ color: "var(--text-2)" }}>{fmtDate(u.created_at)}</span>
                <span className="text-[11px] text-right font-mono" style={{ color: "var(--text-3)" }}>
                  {u.file_size ? fmtBytes(u.file_size) : "—"}
                </span>
                <span className="flex justify-center">
                  <Badge label="ES" active={u.indexed_es} title={u.indexed_es ? "In Elasticsearch indexiert" : "Nicht in ES"} />
                </span>
                <span className="flex justify-center">
                  <Badge label="SQL" active={u.indexed_mysql} title={u.indexed_mysql ? "Tabellarische Daten in MySQL" : "Kein MySQL-Index"} />
                </span>
                <span className="flex justify-center">
                  <Badge label="Graph" active={!!u.enriched_memory} title={u.enriched_memory ? "Als Memory im Knowledge Graph" : "Nicht im Graph"} />
                </span>
                <div className="flex justify-end">
                  {u.exists_on_disk && (
                    <a
                      href={`/api/${instance}/files/upload-download?upload_id=${encodeURIComponent(u.upload_id)}`}
                      download={u.filename}
                      title="Herunterladen"
                      className="text-[12px] px-2 py-1 rounded transition-colors"
                      style={{ border: "1px solid var(--border)", color: "var(--text-2)" }}
                      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = "var(--border-strong)"; (e.currentTarget as HTMLElement).style.color = "var(--text)"; }}
                      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = "var(--border)"; (e.currentTarget as HTMLElement).style.color = "var(--text-2)"; }}
                    >
                      ↓
                    </a>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* ── Mobile card list (<md) ── */}
          <div className="md:hidden space-y-2">
            {filtered.map((u) => (
              <div
                key={u.upload_id}
                className="rounded-md px-3 py-3"
                style={{ border: "1px solid var(--border)", backgroundColor: "var(--bg-elevated)" }}
              >
                <div className="flex items-start justify-between gap-2 min-w-0">
                  <p className="text-[13px] font-medium truncate flex-1" style={{ color: "var(--text)" }} title={u.filename}>
                    {u.filename}
                  </p>
                  <MediaBadge type={u.media_type} />
                </div>
                {u.caption && (
                  <p className="text-[11px] mt-1 line-clamp-2" style={{ color: "var(--text-3)" }}>{u.caption}</p>
                )}
                <div className="flex items-center gap-2 mt-2 flex-wrap">
                  <span className="text-[11px] font-mono" style={{ color: "var(--text-3)" }}>
                    {u.file_size ? fmtBytes(u.file_size) : "—"}
                  </span>
                  <span className="text-[11px]" style={{ color: "var(--text-3)" }}>·</span>
                  <span className="text-[11px]" style={{ color: "var(--text-3)" }}>{fmtDate(u.created_at)}</span>
                  <span className="ml-auto flex items-center gap-1.5">
                    <Badge label="ES" active={u.indexed_es} />
                    <Badge label="SQL" active={u.indexed_mysql} />
                    <Badge label="Graph" active={!!u.enriched_memory} />
                  </span>
                </div>
                {u.exists_on_disk && (
                  <div className="mt-2">
                    <a
                      href={`/api/${instance}/files/upload-download?upload_id=${encodeURIComponent(u.upload_id)}`}
                      download={u.filename}
                      className="inline-flex text-[12px] px-3 py-1.5 rounded transition-colors"
                      style={{ border: "1px solid var(--border)", color: "var(--text-2)" }}
                      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = "var(--border-strong)"; (e.currentTarget as HTMLElement).style.color = "var(--text)"; }}
                      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = "var(--border)"; (e.currentTarget as HTMLElement).style.color = "var(--text-2)"; }}
                    >
                      ↓ Herunterladen
                    </a>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// CREATIONS TAB
// ══════════════════════════════════════════════════════════════════════════════

function CreationsTab({ instance }: { instance: string }) {
  const [files, setFiles] = useState<CreationFile[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`/api/${instance}/files/creations`)
      .then(r => r.json())
      .then(data => {
        if (Array.isArray(data)) setFiles(data);
        else setError(data.error ?? "Error.");
      })
      .catch(() => setError("Netzwerkfehler."))
      .finally(() => setIsLoading(false));
  }, [instance]);

  if (isLoading) return <div className="flex justify-center py-12"><Spinner /></div>;
  if (error) return <p className="text-[13px]" style={{ color: "var(--danger)" }}>{error}</p>;
  if (files.length === 0) return (
    <div className="flex flex-col items-center justify-center py-16 gap-3" style={{ color: "var(--text-3)" }}>
      <span style={{ fontSize: 36 }}>📂</span>
      <p className="text-[13px]">Noch keine generierten Dateien.</p>
      <p className="text-[12px]">Claude legt hier Dateien ab, die er für dich erstellt.</p>
    </div>
  );

  return (
    <div>
      {/* Desktop table */}
      <div className="hidden md:block space-y-px">
        <div
          className="grid text-[10px] uppercase tracking-widest px-3 py-1.5 rounded-t-md"
          style={{
            gridTemplateColumns: "2fr 60px 120px 70px 48px",
            color: "var(--text-3)",
            backgroundColor: "var(--bg-muted)",
            borderBottom: "1px solid var(--border)",
          }}
        >
          <span>Datei</span><span>Typ</span><span>Datum</span>
          <span className="text-right">Größe</span><span></span>
        </div>
        {files.map(f => {
          const ext = f.filename.split(".").pop()?.toLowerCase() ?? "";
          return (
            <div
              key={f.path}
              className="grid items-center px-3 py-2.5 transition-colors"
              style={{
                gridTemplateColumns: "2fr 60px 120px 70px 48px",
                borderBottom: "1px solid var(--border)",
                backgroundColor: "var(--bg)",
              }}
              onMouseEnter={e => (e.currentTarget as HTMLElement).style.backgroundColor = "var(--bg-elevated)"}
              onMouseLeave={e => (e.currentTarget as HTMLElement).style.backgroundColor = "var(--bg)"}
            >
              <div className="flex items-center gap-2 min-w-0">
                <span>{fileIcon(f.filename)}</span>
                <span className="text-[12px] truncate" style={{ color: "var(--text)" }} title={f.filename}>
                  {f.filename}
                </span>
              </div>
              <span
                className="text-[10px] uppercase px-1.5 py-px rounded font-mono inline-flex items-center w-fit"
                style={{ backgroundColor: "var(--bg-muted)", color: "var(--text-3)", border: "1px solid var(--border)" }}
              >
                {ext}
              </span>
              <span className="text-[11px]" style={{ color: "var(--text-2)" }}>
                {fmtModified(f.modified)}
              </span>
              <span className="text-[11px] text-right font-mono" style={{ color: "var(--text-3)" }}>
                {fmtBytes(f.size)}
              </span>
              <div className="flex justify-end">
                <a
                  href={`/api/${instance}/files/download?path=${encodeURIComponent(f.path)}`}
                  download={f.filename}
                  className="text-[12px] px-2 py-1 rounded transition-colors"
                  style={{ border: "1px solid var(--border)", color: "var(--text-2)" }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = "var(--border-strong)"; (e.currentTarget as HTMLElement).style.color = "var(--text)"; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = "var(--border)"; (e.currentTarget as HTMLElement).style.color = "var(--text-2)"; }}
                >
                  ↓
                </a>
              </div>
            </div>
          );
        })}
      </div>
      {/* Mobile */}
      <div className="md:hidden space-y-2">
        {files.map(f => (
          <div
            key={f.path}
            className="flex items-center justify-between gap-3 rounded-md px-3 py-3"
            style={{ border: "1px solid var(--border)", backgroundColor: "var(--bg-elevated)" }}
          >
            <div className="flex items-center gap-2 min-w-0">
              <span>{fileIcon(f.filename)}</span>
              <div className="min-w-0">
                <p className="text-[13px] font-medium truncate" style={{ color: "var(--text)" }}>{f.filename}</p>
                <p className="text-[11px] mt-0.5" style={{ color: "var(--text-3)" }}>
                  {fmtBytes(f.size)} · {fmtModified(f.modified)}
                </p>
              </div>
            </div>
            <a
              href={`/api/${instance}/files/download?path=${encodeURIComponent(f.path)}`}
              download={f.filename}
              className="flex-shrink-0 text-[12px] px-3 py-1.5 rounded transition-colors"
              style={{ border: "1px solid var(--border)", color: "var(--text-2)" }}
              onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = "var(--border-strong)"; (e.currentTarget as HTMLElement).style.color = "var(--text)"; }}
              onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = "var(--border)"; (e.currentTarget as HTMLElement).style.color = "var(--text-2)"; }}
            >
              ↓
            </a>
          </div>
        ))}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// WORKSPACE TAB
// ══════════════════════════════════════════════════════════════════════════════

function WorkspaceTab({ instance }: { instance: string }) {
  const [listing, setListing] = useState<WorkspaceListing | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentPath, setCurrentPath] = useState("");
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<FileContent | null>(null);
  const [fileLoading, setFileLoading] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const [monacoTheme, setMonacoTheme] = useState("vs-dark");
  // Mobile: "tree" shows file browser, "editor" shows code view
  const [mobilePanel, setMobilePanel] = useState<"tree" | "editor">("tree");

  // Sync monaco theme with document theme
  useEffect(() => {
    const update = () => {
      const isDark = document.documentElement.getAttribute("data-theme") === "dark" ||
        (document.documentElement.getAttribute("data-theme") === "system" &&
          window.matchMedia("(prefers-color-scheme: dark)").matches) ||
        (!document.documentElement.getAttribute("data-theme") &&
          window.matchMedia("(prefers-color-scheme: dark)").matches);
      setMonacoTheme(isDark ? "vs-dark" : "vs");
    };
    update();
    const obs = new MutationObserver(update);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "class"] });
    return () => obs.disconnect();
  }, []);

  const loadDir = useCallback((path: string) => {
    setIsLoading(true);
    setError(null);
    setSelectedFile(null);
    setFileContent(null);
    fetch(`/api/${instance}/files/workspace${path ? `?path=${encodeURIComponent(path)}` : ""}`)
      .then((r) => r.json())
      .then((data) => {
        if (data.entries !== undefined) {
          setListing(data);
          setCurrentPath(data.path);
        } else {
          setError(data.error ?? "Error.");
        }
      })
      .catch(() => setError("Netzwerkfehler."))
      .finally(() => setIsLoading(false));
  }, [instance]);

  useEffect(() => { loadDir(""); }, [loadDir]);

  const loadFile = (path: string) => {
    setSelectedFile(path);
    setFileLoading(true);
    setFileError(null);
    setFileContent(null);
    setMobilePanel("editor");
    fetch(`/api/${instance}/files/read?path=${encodeURIComponent(path)}`)
      .then(async (r) => {
        if (r.status === 415) {
          const filename = path.split("/").pop() ?? path;
          setFileContent({
            path,
            name: filename,
            content: "",
            size: 0,
            mime_type: null,
            language: null,
            render_type: "binary",
            previewable: false,
          });
          return;
        }
        const data = await r.json();
        if (data.render_type || data.content !== undefined) setFileContent(data);
        else setFileError(data.error ?? data.detail ?? "Fehler.");
      })
      .catch(() => setFileError("Netzwerkfehler."))
      .finally(() => setFileLoading(false));
  };

  // Breadcrumb from currentPath
  const breadcrumbs = currentPath
    ? currentPath.split("/").filter(Boolean).reduce<{ label: string; path: string }[]>((acc, part) => {
      const prev = acc[acc.length - 1]?.path ?? "";
      acc.push({ label: part, path: prev ? `${prev}/${part}` : part });
      return acc;
    }, [])
    : [];

  return (
    <div>
      {/* Mobile panel toggle */}
      <div
        className="md:hidden flex mb-3"
        style={{ border: "1px solid var(--border)", borderRadius: "6px", overflow: "hidden" }}
      >
        {(["tree", "editor"] as const).map((panel) => (
          <button
            key={panel}
            onClick={() => setMobilePanel(panel)}
            className="flex-1 py-2 text-[12px] transition-colors"
            style={{
              backgroundColor: mobilePanel === panel ? "var(--bg-subtle)" : "var(--bg)",
              color: mobilePanel === panel ? "var(--text)" : "var(--text-3)",
              fontWeight: mobilePanel === panel ? 500 : 400,
            }}
          >
            {panel === "tree" ? "Dateien" : selectedFile ? "Editor" : "Editor"}
          </button>
        ))}
      </div>

    <div className="flex gap-0" style={{ minHeight: "500px" }}>
      {/* File tree */}
      <div
        className={[
          "flex-shrink-0 overflow-y-auto rounded-l-md",
          // Mobile: full width, hidden when editor panel active
          mobilePanel === "editor" ? "hidden md:flex md:flex-col" : "w-full md:w-64",
          "md:flex md:flex-col",
        ].join(" ")}
        style={{ border: "1px solid var(--border)", borderRight: "none", backgroundColor: "var(--bg-elevated)" }}
      >
        {/* Breadcrumb */}
        <div
          className="px-3 py-2 flex items-center gap-1 flex-wrap"
          style={{ borderBottom: "1px solid var(--border)" }}
        >
          <button
            onClick={() => loadDir("")}
            className="text-[11px] transition-colors"
            style={{ color: currentPath ? "var(--accent)" : "var(--text)", fontWeight: currentPath ? 400 : 500 }}
            onMouseEnter={(e) => (e.currentTarget as HTMLElement).style.color = "var(--text)"}
            onMouseLeave={(e) => (e.currentTarget as HTMLElement).style.color = currentPath ? "var(--accent)" : "var(--text)"}
          >
            workspace
          </button>
          {breadcrumbs.map((bc, i) => (
            <span key={bc.path} className="flex items-center gap-1">
              <span style={{ color: "var(--text-3)", fontSize: 10 }}>/</span>
              <button
                onClick={() => loadDir(bc.path)}
                className="text-[11px] transition-colors"
                style={{ color: i === breadcrumbs.length - 1 ? "var(--text)" : "var(--accent)", fontWeight: i === breadcrumbs.length - 1 ? 500 : 400 }}
                onMouseEnter={(e) => (e.currentTarget as HTMLElement).style.color = "var(--text)"}
                onMouseLeave={(e) => (e.currentTarget as HTMLElement).style.color = i === breadcrumbs.length - 1 ? "var(--text)" : "var(--accent)"}
              >
                {bc.label}
              </button>
            </span>
          ))}
        </div>

        {/* Back button */}
        {currentPath && (
          <button
            onClick={() => {
              const parts = currentPath.split("/").filter(Boolean);
              parts.pop();
              loadDir(parts.join("/"));
            }}
            className="w-full flex items-center gap-2 px-3 py-1.5 text-[12px] transition-colors"
            style={{ color: "var(--text-3)" }}
            onMouseEnter={(e) => (e.currentTarget as HTMLElement).style.color = "var(--text)"}
            onMouseLeave={(e) => (e.currentTarget as HTMLElement).style.color = "var(--text-3)"}
          >
            <span>←</span>
            <span>..</span>
          </button>
        )}

        {/* Entries */}
        {isLoading ? (
          <div className="flex justify-center py-8"><Spinner className="h-3.5 w-3.5" /></div>
        ) : error ? (
          <p className="px-3 py-3 text-[12px]" style={{ color: "var(--danger)" }}>{error}</p>
        ) : listing?.entries.length === 0 ? (
          <p className="px-3 py-3 text-[12px]" style={{ color: "var(--text-3)" }}>Leer.</p>
        ) : (
          <div>
            {listing?.entries.map((entry) => {
              const isActive = selectedFile === entry.path;
              return (
                <div key={entry.path} className="flex items-center group">
                  <button
                    onClick={() => entry.is_dir ? loadDir(entry.path) : loadFile(entry.path)}
                    className="flex-1 flex items-center gap-2 px-3 py-1.5 text-[12px] text-left transition-colors min-w-0"
                    style={{
                      color: isActive ? "var(--text)" : "var(--text-2)",
                      backgroundColor: isActive ? "var(--bg-subtle)" : "transparent",
                    }}
                    onMouseEnter={(e) => { if (!isActive) (e.currentTarget as HTMLElement).style.backgroundColor = "var(--bg-subtle)"; }}
                    onMouseLeave={(e) => { if (!isActive) (e.currentTarget as HTMLElement).style.backgroundColor = "transparent"; }}
                  >
                    <span className="flex-shrink-0" style={{ color: entry.is_dir ? "var(--accent)" : "var(--text-3)" }}>
                      {entry.is_dir ? <FolderIcon /> : <FileIcon />}
                    </span>
                    <span className="truncate">{entry.name}</span>
                    {!entry.is_dir && entry.size !== null && (
                      <span className="text-[10px] flex-shrink-0 ml-auto" style={{ color: "var(--text-3)" }}>
                        {fmtBytes(entry.size)}
                      </span>
                    )}
                    {entry.is_dir && (
                      <span className="flex-shrink-0 ml-auto" style={{ color: "var(--text-3)" }}>
                        <ChevronIcon dir="right" />
                      </span>
                    )}
                  </button>
                  {!entry.is_dir && (
                    <a
                      href={`/api/${instance}/files/download?path=${encodeURIComponent(entry.path)}&workspace=true`}
                      download={entry.name}
                      title="Herunterladen"
                      onClick={e => e.stopPropagation()}
                      className="opacity-0 group-hover:opacity-100 flex-shrink-0 px-2 py-1.5 text-[11px] transition-opacity"
                      style={{ color: "var(--text-3)" }}
                      onMouseEnter={e => (e.currentTarget as HTMLElement).style.color = "var(--text)"}
                      onMouseLeave={e => (e.currentTarget as HTMLElement).style.color = "var(--text-3)"}
                    >
                      ↓
                    </a>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Editor panel */}
      <div
        className={[
          "min-w-0 overflow-hidden rounded-r-md flex flex-col",
          // Mobile: full width, hidden when tree panel active
          mobilePanel === "tree" ? "hidden md:flex md:flex-1" : "flex flex-1",
          "md:flex md:flex-1",
        ].join(" ")}
        style={{ border: "1px solid var(--border)", backgroundColor: "var(--bg)" }}
      >
        {!selectedFile ? (
          <div className="flex flex-col items-center justify-center h-full gap-2" style={{ color: "var(--text-3)" }}>
            <FileIcon />
            <p className="text-[12px]">Datei auswählen</p>
          </div>
        ) : fileLoading ? (
          <div className="flex justify-center items-center h-full"><Spinner /></div>
        ) : fileError ? (
          <div className="flex flex-col items-center justify-center h-full gap-2">
            <p className="text-[13px]" style={{ color: "var(--danger)" }}>{fileError}</p>
          </div>
        ) : fileContent ? (
          <>
            <div
              className="px-3 py-2 flex items-center justify-between flex-shrink-0"
              style={{ borderBottom: "1px solid var(--border)" }}
            >
              <div className="flex items-center gap-2 min-w-0">
                <span style={{ color: "var(--text-3)" }}><FileIcon /></span>
                <span className="text-[12px] font-mono truncate" style={{ color: "var(--text-2)" }}>
                  {fileContent.path}
                </span>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                {fileContent.size > 0 && (
                  <span className="text-[11px] font-mono" style={{ color: "var(--text-3)" }}>
                    {fmtBytes(fileContent.size)}
                  </span>
                )}
                {fileContent.language && (
                  <span
                    className="text-[10px] px-1.5 py-px rounded font-mono"
                    style={{ backgroundColor: "var(--bg-muted)", color: "var(--text-3)", border: "1px solid var(--border)" }}
                  >
                    {fileContent.language}
                  </span>
                )}
                <a
                  href={`/api/${instance}/files/download?path=${encodeURIComponent(fileContent.path)}&workspace=true`}
                  download={fileContent.name}
                  className="text-[11px] px-2 py-1 rounded transition-colors"
                  style={{ border: "1px solid var(--border)", color: "var(--text-2)" }}
                  onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.borderColor = "var(--border-strong)"; (e.currentTarget as HTMLElement).style.color = "var(--text)"; }}
                  onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.borderColor = "var(--border)"; (e.currentTarget as HTMLElement).style.color = "var(--text-2)"; }}
                >
                  ↓
                </a>
              </div>
            </div>
            <div className="flex-1 min-h-0">
              <FileRenderer file={fileContent} instance={instance} monacoTheme={monacoTheme} />
            </div>
          </>
        ) : null}
      </div>
    </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// PAGE
// ══════════════════════════════════════════════════════════════════════════════

type Tab = "uploads" | "creations" | "workspace";

function FilesContent() {
  const { instance } = useParams<{ instance: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const tab = (searchParams.get("tab") as Tab) ?? "uploads";

  const setTab = (t: Tab) => router.replace(`/${instance}/files?tab=${t}`);

  const tabs: { id: Tab; label: string }[] = [
    { id: "uploads", label: "Uploads" },
    { id: "creations", label: "Creations" },
    { id: "workspace", label: "Workspace" },
  ];

  return (
    <div className="flex-1 overflow-y-auto" style={{ backgroundColor: "var(--bg)" }}>
      <div className="max-w-5xl mx-auto px-6 py-8">
        {/* Header */}
        <div className="mb-6 flex items-center gap-3">
          <h1 className="text-[20px] font-semibold tracking-tight" style={{ color: "var(--text)" }}>
            Dateien
          </h1>
        </div>

        {/* Tab navigation */}
        <div className="flex items-center gap-0 mb-8" style={{ borderBottom: "1px solid var(--border)" }}>
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className="px-4 py-2.5 text-[13px] transition-colors relative"
              style={{ color: tab === t.id ? "var(--text)" : "var(--text-3)", fontWeight: tab === t.id ? 500 : 400 }}
            >
              {t.label}
              {tab === t.id && (
                <span className="absolute bottom-0 left-0 right-0 h-px" style={{ backgroundColor: "var(--text)" }} />
              )}
            </button>
          ))}
        </div>

        {/* Tab content */}
        {tab === "uploads" && <UploadsTab instance={instance} />}
        {tab === "creations" && <CreationsTab instance={instance} />}
        {tab === "workspace" && <WorkspaceTab instance={instance} />}
      </div>
    </div>
  );
}

export default function FilesPage() {
  return (
    <Suspense fallback={<div className="flex-1 flex justify-center items-center"><Spinner /></div>}>
      <FilesContent />
    </Suspense>
  );
}
