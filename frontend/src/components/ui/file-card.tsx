"use client";

import { useParams } from "next/navigation";

const EXT_ICONS: Record<string, string> = {
  docx: "📄",
  xlsx: "📊",
  csv:  "📋",
  pdf:  "📕",
  txt:  "📝",
  md:   "📝",
  mp3:  "🎵",
  wav:  "🎵",
  ogg:  "🎵",
  png:  "🖼️",
  jpg:  "🖼️",
  jpeg: "🖼️",
};

function extOf(filename: string) {
  return filename.split(".").pop()?.toLowerCase() ?? "";
}

interface FileCardProps {
  path: string;
}

/** Renders a download card for a file path under /root/creations/. */
export function FileCard({ path }: FileCardProps) {
  const params = useParams<{ instance: string }>();
  const instance = params?.instance ?? "";

  const filename = path.split("/").pop() ?? path;
  const ext = extOf(filename);
  const icon = EXT_ICONS[ext] ?? "📎";

  const downloadUrl = `/api/${instance}/files/download?path=${encodeURIComponent(path)}`;

  return (
    <a
      href={downloadUrl}
      download={filename}
      className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-[13px] transition-colors no-underline"
      style={{
        border: "1px solid var(--border)",
        color: "var(--text)",
        backgroundColor: "var(--bg-subtle)",
      }}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLElement).style.borderColor = "var(--border-strong)";
        (e.currentTarget as HTMLElement).style.backgroundColor = "var(--bg-hover, var(--bg-subtle))";
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLElement).style.borderColor = "var(--border)";
        (e.currentTarget as HTMLElement).style.backgroundColor = "var(--bg-subtle)";
      }}
    >
      <span>{icon}</span>
      <span className="font-medium">{filename}</span>
      <span style={{ color: "var(--text-3)", fontSize: "11px" }}>↓</span>
    </a>
  );
}

/** Returns true if the string looks like a generated file path. */
export function isCreationsPath(s: string): boolean {
  return /^\/root\/creations\/\S+/.test(s.trim());
}
