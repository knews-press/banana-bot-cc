"use client";

import { useParams, useSearchParams, useRouter } from "next/navigation";
import { useState, useEffect, useCallback, Suspense } from "react";
import { useStats } from "@/hooks/use-stats";
import { useDailyStats } from "@/hooks/use-daily-stats";
import { useProfile } from "@/hooks/use-profile";
import { Spinner } from "@/components/ui/spinner";
import type { UserPreferences } from "@/types";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, Legend, CartesianGrid
} from "recharts";

// ── Helpers ────────────────────────────────────────────────────────────────
function fmtTokens(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "k";
  return String(n);
}
function fmtCost(n: number): string {
  return "$" + n.toFixed(n >= 1 ? 2 : 4);
}
function shortModel(m: string): string {
  return m.replace(/claude-?/i, "").replace(/20\d{6}/, "").replace(/-+$/, "").trim() || m;
}
// "2026-04" → "April 2026"
function monthLabel(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("de-DE", { month: "long", year: "numeric" });
}
// Returns the Monday of the week that is `offset` weeks from today (0 = current week)
function getWeekStart(offset: number): Date {
  const now = new Date();
  const dow = now.getDay() === 0 ? 7 : now.getDay(); // Mon=1 … Sun=7
  const monday = new Date(now);
  monday.setDate(now.getDate() - dow + 1 + offset * 7);
  monday.setHours(0, 0, 0, 0);
  return monday;
}
// ISO week number for a Date
function isoWeek(d: Date): number {
  const tmp = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  tmp.setUTCDate(tmp.getUTCDate() + 4 - (tmp.getUTCDay() || 7));
  const yearStart = new Date(Date.UTC(tmp.getUTCFullYear(), 0, 1));
  return Math.ceil((((tmp.getTime() - yearStart.getTime()) / 86400000) + 1) / 7);
}
// "KW 15 · 2026"
function weekLabel(offset: number): string {
  const mon = getWeekStart(offset);
  return `KW\u00a0${isoWeek(mon)} · ${mon.getFullYear()}`;
}
// "2026-04-07" → "Mo 07.04"
function weekDayLabel(dateStr: string): string {
  const dt = new Date(dateStr + "T12:00:00");
  const day = dt.toLocaleDateString("de-DE", { weekday: "short" }).replace(".", "");
  const dm = dt.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" });
  return `${day} ${dm}`;
}
// "2026-04-09" → "09.04"
function shortDate(d: string): string {
  const dt = new Date(d + "T12:00:00");
  return dt.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" });
}
// "2026-04-09" → day number "09"
function dayNum(d: string): string {
  return d.split("-")[2];
}
// "2026-04-09" → "YYYY-MM"
function toYM(d: string): string { return d.slice(0, 7); }
// "2026-04" → "Jan 26"  (short month for all-time x-axis)
function shortMonth(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  const s = new Date(y, m - 1, 1).toLocaleDateString("de-DE", { month: "short" });
  return s.replace(".", "") + " " + String(y).slice(2);
}

// ── Karte ──────────────────────────────────────────────────────────────────
function KPI({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="py-3">
      <p className="text-[11px] uppercase tracking-wide mb-1" style={{ color: "var(--text-3)" }}>{label}</p>
      <p className="text-[22px] font-semibold font-mono tabular-nums leading-none" style={{ color: "var(--text)" }}>{value}</p>
      {sub && <p className="text-[12px] mt-0.5" style={{ color: "var(--text-3)" }}>{sub}</p>}
    </div>
  );
}

// ── Chart tooltip ──────────────────────────────────────────────────────────
function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ name: string; value: number; color: string }>; label?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="text-[12px] rounded-md px-3 py-2 shadow-sm" style={{ backgroundColor: "var(--bg-elevated)", border: "1px solid var(--border)", color: "var(--text)" }}>
      <p className="font-medium mb-1" style={{ color: "var(--text-2)" }}>{label}</p>
      {payload.map((p) => (
        <p key={p.name} style={{ color: p.color }}>
          {p.name}: <span className="font-mono">{typeof p.value === "number" && p.value < 1 ? fmtCost(p.value) : fmtTokens(p.value)}</span>
        </p>
      ))}
    </div>
  );
}

// ── MODEL COLOURS ──────────────────────────────────────────────────────────
const MODEL_COLORS = ["#78716c", "#a8a29e", "#57534e", "#44403c", "#d6d3d1", "#292524"];

// ── Interactive legend click handler ───────────────────────────────────────
function useLegendToggle() {
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const toggle = (e: any) => {
    const key = String(e.dataKey ?? e.value ?? "");
    setHidden((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  };
  const isHidden = (key: string) => hidden.has(key);
  const legendStyle = (key: string): React.CSSProperties => ({
    fontSize: 11,
    opacity: hidden.has(key) ? 0.35 : 1,
    textDecoration: hidden.has(key) ? "line-through" : "none",
    cursor: "pointer",
  });
  return { toggle, isHidden, legendStyle };
}

// ── Range type ─────────────────────────────────────────────────────────────
type Range = "7" | "30" | "month" | "all";

// ══════════════════════════════════════════════════════════════════════════
// STATS TAB
// ══════════════════════════════════════════════════════════════════════════
function StatsTab({ instance }: { instance: string }) {
  const { stats } = useStats(instance);
  const { data, isLoading } = useDailyStats(instance);
  const [range, setRange] = useState<Range>("30");
  // monthOffset: 0 = current month, -1 = previous, etc.
  const [monthOffset, setMonthOffset] = useState(0);
  // weekOffset: 0 = current week, -1 = previous, etc.
  const [weekOffset, setWeekOffset] = useState(0);
  const tokenLegend = useLegendToggle();
  const costLegend = useLegendToggle();

  if (isLoading || !stats || !data) {
    return <div className="flex justify-center py-16"><Spinner /></div>;
  }

  // ── Compute the active month label & filter ─────────────────────────────
  const now = new Date();
  const activeDate = new Date(now.getFullYear(), now.getMonth() + monthOffset, 1);
  const activeYM = `${activeDate.getFullYear()}-${String(activeDate.getMonth() + 1).padStart(2, "0")}`;

  // ── Compute active week bounds ──────────────────────────────────────────
  const weekStart = getWeekStart(weekOffset);
  const weekEnd = new Date(weekStart);
  weekEnd.setDate(weekStart.getDate() + 7);

  // ── Filter rows by selected range ───────────────────────────────────────
  const filtered = (() => {
    if (range === "all") return data.daily;
    if (range === "month") return data.daily.filter((d) => toYM(d.date) === activeYM);
    if (range === "7") return data.daily.filter((d) => {
      const dt = new Date(d.date + "T12:00:00");
      return dt >= weekStart && dt < weekEnd;
    });
    // "30": rolling last-30-days
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - 30);
    return data.daily.filter((d) => new Date(d.date + "T12:00:00") >= cutoff);
  })();

  // ── X-axis key & label ──────────────────────────────────────────────────
  // For "all": aggregate by month → key = "YYYY-MM"
  // For "month": key = day number "DD"
  // For "7"/"30": key = "DD.MM"
  const xKey = range === "all" ? "_ym" : "date";

  // ── Token chart data ────────────────────────────────────────────────────
  const tokenByKey: Record<string, { date: string; _ym?: string; input: number; output: number; cacheWrite: number; cacheRead: number }> = {};
  for (const row of (range === "all" ? data.daily : filtered)) {
    const key = range === "all" ? toYM(row.date) : row.date;
    if (!tokenByKey[key]) tokenByKey[key] = {
      date: range === "month" ? dayNum(row.date) : range === "all" ? shortMonth(key) : range === "7" ? weekDayLabel(row.date) : shortDate(row.date),
      _ym: range === "all" ? key : undefined,
      input: 0, output: 0, cacheWrite: 0, cacheRead: 0,
    };
    tokenByKey[key].input += row.input_tokens;
    tokenByKey[key].output += row.output_tokens;
    tokenByKey[key].cacheWrite += row.cache_creation_tokens;
    tokenByKey[key].cacheRead += row.cache_read_tokens;
  }
  const tokenChartData = Object.values(tokenByKey);

  // ── Cost chart data ─────────────────────────────────────────────────────
  const costModels = [...new Set((range === "all" ? data.daily : filtered).map((d) => shortModel(d.model)))];
  const costByKey: Record<string, Record<string, unknown>> = {};
  for (const row of (range === "all" ? data.daily : filtered)) {
    const key = range === "all" ? toYM(row.date) : row.date;
    const sm = shortModel(row.model);
    if (!costByKey[key]) costByKey[key] = {
      date: range === "month" ? dayNum(row.date) : range === "all" ? shortMonth(key) : range === "7" ? weekDayLabel(row.date) : shortDate(row.date),
    };
    costByKey[key][sm] = ((costByKey[key][sm] as number) ?? 0) + row.cost;
  }
  const costChartData = Object.values(costByKey);

  // ── Range-aware KPIs (from filtered rows) ──────────────────────────────
  const rangeMessages = filtered.reduce((s, r) => s + r.messages, 0);
  const rangeCost = filtered.reduce((s, r) => s + r.cost, 0);
  const rangeTokens = filtered.reduce((s, r) => s + r.input_tokens + r.output_tokens + r.cache_creation_tokens + r.cache_read_tokens, 0);
  const avgCostPerMsg = rangeMessages > 0 ? rangeCost / rangeMessages : 0;

  // Tool usage is all-time (daily rows don't carry per-tool breakdown)
  const toolsToShow = data.tools;

  return (
    <div className="space-y-8">
      {/* KPIs — range-aware */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-px" style={{ borderTop: "1px solid var(--border)", borderBottom: "1px solid var(--border)" }}>
        {[
          { label: "Messages", value: String(rangeMessages) },
          { label: "Tokens", value: fmtTokens(rangeTokens) },
          { label: "Cost", value: fmtCost(rangeCost) },
          { label: "Avg cost/message", value: rangeMessages > 0 ? fmtCost(avgCostPerMsg) : "—" },
        ].map((k, i) => (
          <div key={i} className="px-4 py-3 sm:px-6" style={{ borderRight: i < 3 ? "1px solid var(--border)" : "none" }}>
            <KPI {...k} />
          </div>
        ))}
      </div>

      {/* Range selector */}
      <div className="flex flex-wrap items-center gap-1">
        {/* 7T button */}
        <button onClick={() => setRange("7")}
          className="px-3 py-1 rounded text-[12px] transition-colors"
          style={{ color: range === "7" ? "var(--text)" : "var(--text-3)", backgroundColor: range === "7" ? "var(--bg-muted)" : "transparent", fontWeight: range === "7" ? 500 : 400 }}>
          7T
        </button>
        {/* 30T button */}
        <button onClick={() => setRange("30")}
          className="px-3 py-1 rounded text-[12px] transition-colors"
          style={{ color: range === "30" ? "var(--text)" : "var(--text-3)", backgroundColor: range === "30" ? "var(--bg-muted)" : "transparent", fontWeight: range === "30" ? 500 : 400 }}>
          30T
        </button>
        {/* Month button */}
        <button onClick={() => setRange("month")}
          className="px-3 py-1 rounded text-[12px] transition-colors"
          style={{ color: range === "month" ? "var(--text)" : "var(--text-3)", backgroundColor: range === "month" ? "var(--bg-muted)" : "transparent", fontWeight: range === "month" ? 500 : 400 }}>
          Monat
        </button>
        {/* Gesamt button */}
        <button onClick={() => setRange("all")}
          className="px-3 py-1 rounded text-[12px] transition-colors"
          style={{ color: range === "all" ? "var(--text)" : "var(--text-3)", backgroundColor: range === "all" ? "var(--bg-muted)" : "transparent", fontWeight: range === "all" ? 500 : 400 }}>
          Gesamt
        </button>

        {/* Week navigator — only visible when range === "7" */}
        {range === "7" && (
          <div className="flex items-center gap-1 ml-2 pl-2" style={{ borderLeft: "1px solid var(--border)" }}>
            <button onClick={() => setWeekOffset((o) => o - 1)}
              className="w-6 h-6 flex items-center justify-center rounded text-[13px] transition-colors"
              style={{ color: "var(--text-2)" }}>‹</button>
            <span className="text-[12px] px-1 tabular-nums" style={{ color: "var(--text-2)", minWidth: "7rem", textAlign: "center" }}>
              {weekLabel(weekOffset)}
            </span>
            <button onClick={() => setWeekOffset((o) => Math.min(o + 1, 0))}
              disabled={weekOffset >= 0}
              className="w-6 h-6 flex items-center justify-center rounded text-[13px] transition-colors disabled:opacity-30"
              style={{ color: "var(--text-2)" }}>›</button>
          </div>
        )}

        {/* Month navigator — only visible when range === "month" */}
        {range === "month" && (
          <div className="flex items-center gap-1 ml-2 pl-2" style={{ borderLeft: "1px solid var(--border)" }}>
            <button onClick={() => setMonthOffset((o) => o - 1)}
              className="w-6 h-6 flex items-center justify-center rounded text-[13px] transition-colors"
              style={{ color: "var(--text-2)" }}>‹</button>
            <span className="text-[12px] px-1 tabular-nums" style={{ color: "var(--text-2)", minWidth: "7rem", textAlign: "center" }}>
              {monthLabel(activeYM)}
            </span>
            <button onClick={() => setMonthOffset((o) => Math.min(o + 1, 0))}
              disabled={monthOffset >= 0}
              className="w-6 h-6 flex items-center justify-center rounded text-[13px] transition-colors disabled:opacity-30"
              style={{ color: "var(--text-2)" }}>›</button>
          </div>
        )}
      </div>

      {/* Token chart */}
      {tokenChartData.length > 0 && (
        <section>
          <h3 className="text-[13px] font-medium mb-4" style={{ color: "var(--text-2)" }}>Token usage</h3>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={tokenChartData} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: "var(--text-3)" }} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 11, fill: "var(--text-3)" }} tickFormatter={fmtTokens} />
              <Tooltip content={<ChartTooltip />} />
              <Legend
                wrapperStyle={{ fontSize: 11 }}
                onClick={tokenLegend.toggle}
                formatter={(value) => <span style={tokenLegend.legendStyle(value)}>{value}</span>}
              />
              <Line type="monotone" dataKey="input" name="Input" stroke="#78716c" strokeWidth={1.5} dot={false} hide={tokenLegend.isHidden("input")} />
              <Line type="monotone" dataKey="output" name="Output" stroke="#44403c" strokeWidth={1.5} dot={false} hide={tokenLegend.isHidden("output")} />
              <Line type="monotone" dataKey="cacheWrite" name="Cache Write" stroke="#a8a29e" strokeWidth={1.5} dot={false} strokeDasharray="4 2" hide={tokenLegend.isHidden("cacheWrite")} />
              <Line type="monotone" dataKey="cacheRead" name="Cache Read" stroke="#d6d3d1" strokeWidth={1.5} dot={false} strokeDasharray="2 3" hide={tokenLegend.isHidden("cacheRead")} />
            </LineChart>
          </ResponsiveContainer>
        </section>
      )}

      {/* Cost chart */}
      {costChartData.length > 0 && costModels.length > 0 && (
        <section>
          <h3 className="text-[13px] font-medium mb-4" style={{ color: "var(--text-2)" }}>Cost by model</h3>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={costChartData} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: "var(--text-3)" }} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 11, fill: "var(--text-3)" }} tickFormatter={(v) => "$" + v.toFixed(3)} />
              <Tooltip content={<ChartTooltip />} />
              <Legend
                wrapperStyle={{ fontSize: 11 }}
                onClick={costLegend.toggle}
                formatter={(value) => <span style={costLegend.legendStyle(value)}>{value}</span>}
              />
              {costModels.map((m, i) => (
                <Bar key={m} dataKey={m} stackId="a" fill={MODEL_COLORS[i % MODEL_COLORS.length]} hide={costLegend.isHidden(m)} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </section>
      )}

      {/* Tool usage — range-aware */}
      {toolsToShow.length > 0 && (
        <section>
          <h3 className="text-[13px] font-medium mb-4" style={{ color: "var(--text-2)" }}>Tool-Nutzung</h3>
          <div className="space-y-2">
            {toolsToShow.map((t) => {
              const max = toolsToShow[0].count;
              const pct = (t.count / max) * 100;
              return (
                <div key={t.tool_name} className="flex items-center gap-3">
                  <span className="text-[12px] font-mono w-40 flex-shrink-0 truncate" style={{ color: "var(--text-2)" }}>
                    {t.tool_name.replace("mcp__", "")}
                  </span>
                  <div className="flex-1 h-1 rounded-full overflow-hidden" style={{ backgroundColor: "var(--bg-muted)" }}>
                    <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, backgroundColor: "var(--text-3)" }} />
                  </div>
                  <span className="text-[12px] font-mono w-10 text-right tabular-nums" style={{ color: "var(--text-3)" }}>{t.count}</span>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* Per-model table — from all-time stats */}
      {stats.by_model.length > 0 && (
        <section>
          <h3 className="text-[13px] font-medium mb-3" style={{ color: "var(--text-2)" }}>By model (total)</h3>
          <div style={{ borderTop: "1px solid var(--border)" }}>
            <div className="grid grid-cols-[1fr_auto_auto_auto] gap-x-6 px-1 py-2 text-[11px] uppercase tracking-wide" style={{ color: "var(--text-3)" }}>
              <span>Model</span><span className="text-right">Msgs</span><span className="text-right">Tokens</span><span className="text-right">Cost</span>
            </div>
            {stats.by_model.map((row) => {
              const all = row.input_tokens + row.output_tokens + row.cache_creation_tokens + row.cache_read_tokens;
              return (
                <div key={row.model} className="grid grid-cols-[1fr_auto_auto_auto] gap-x-6 px-1 py-2.5 text-[13px]" style={{ borderTop: "1px solid var(--border)" }}>
                  <span className="font-mono truncate" style={{ color: "var(--text-2)" }}>{shortModel(row.model)}</span>
                  <span className="text-right tabular-nums" style={{ color: "var(--text-3)" }}>{row.messages}</span>
                  <span className="text-right tabular-nums" style={{ color: "var(--text-3)" }}>{fmtTokens(all)}</span>
                  <span className="text-right tabular-nums font-medium" style={{ color: "var(--text)" }}>{fmtCost(row.cost)}</span>
                </div>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}

// ── Shared UI helpers ─────────────────────────────────────────────────────────

const inputClass = "w-full rounded-md px-3 py-2 text-[13px] transition-colors focus:outline-none";
const inputStyle = {
  backgroundColor: "var(--bg-elevated)",
  border: "1px solid var(--border)",
  color: "var(--text)",
} as React.CSSProperties;

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline gap-2">
        <label className="text-[13px] font-medium" style={{ color: "var(--text-2)" }}>{label}</label>
        {hint && <span className="text-[11px]" style={{ color: "var(--text-3)" }}>{hint}</span>}
      </div>
      {children}
    </div>
  );
}

function TextInput({ value, onChange, placeholder, type = "text" }: {
  value: string; onChange: (v: string) => void; placeholder?: string; type?: string;
}) {
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className={inputClass}
      style={inputStyle}
    />
  );
}

function SelectInput({ value, onChange, options }: {
  value: string; onChange: (v: string) => void; options: { value: string; label: string }[];
}) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className={inputClass} style={inputStyle}>
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}

function Toggle({ value, onChange, label }: { value: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button type="button" onClick={() => onChange(!value)}
      className="flex items-center gap-3 py-1 text-[13px] text-left w-full"
      style={{ color: "var(--text-2)" }}>
      <div className="relative w-8 h-4.5 rounded-full transition-colors flex-shrink-0"
        style={{ backgroundColor: value ? "var(--accent)" : "var(--bg-muted)", width: 32, height: 18 }}>
        <div className={`absolute top-0.5 w-3.5 h-3.5 rounded-full bg-white shadow transition-transform ${value ? "translate-x-3.5" : "translate-x-0.5"}`} />
      </div>
      <span>{label}</span>
    </button>
  );
}

// ── TTS voices ────────────────────────────────────────────────────────────────
const GEMINI_VOICES = [
  { value: "Puck", label: "Puck — playful" },
  { value: "Charon", label: "Charon — deep" },
  { value: "Kore", label: "Kore — clear" },
  { value: "Fenrir", label: "Fenrir — strong" },
  { value: "Aoede", label: "Aoede — warm" },
];
const OPENAI_VOICES = [
  { value: "alloy", label: "Alloy — neutral" },
  { value: "echo", label: "Echo — male" },
  { value: "fable", label: "Fable — expressive" },
  { value: "onyx", label: "Onyx — deep" },
  { value: "nova", label: "Nova — female" },
  { value: "shimmer", label: "Shimmer — soft" },
];

function useTTSSettings(instance: string) {
  const [ttsProvider, setTtsProvider] = useState("gemini");
  const [ttsVoice, setTtsVoice] = useState("Puck");
  const [ttsStyle, setTtsStyle] = useState("");
  const [ttsFormat, setTtsFormat] = useState("oga");
  const [ttsSaving, setTtsSaving] = useState(false);
  const [ttsSaved, setTtsSaved] = useState(false);
  const [ttsError, setTtsError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`/api/${instance}/user/tts`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => {
        if (!d) return;
        setTtsProvider(d.provider ?? "gemini");
        setTtsVoice(d.voice ?? "Puck");
        setTtsStyle(d.style_prompt ?? "");
        setTtsFormat(d.output_format ?? "oga");
      })
      .catch(() => {});
  }, [instance]);

  const saveTTS = async () => {
    setTtsSaving(true);
    setTtsError(null);
    setTtsSaved(false);
    try {
      const res = await fetch(`/api/${instance}/user/tts`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: ttsProvider,
          voice: ttsVoice,
          style_prompt: ttsStyle || null,
          output_format: ttsFormat,
        }),
      });
      if (!res.ok) throw new Error("Failed to save.");
      setTtsSaved(true);
      setTimeout(() => setTtsSaved(false), 3000);
    } catch {
      setTtsError("Failed to save TTS settings.");
    } finally {
      setTtsSaving(false);
    }
  };

  const voices = ttsProvider === "openai" ? OPENAI_VOICES : GEMINI_VOICES;

  return { ttsProvider, setTtsProvider, ttsVoice, setTtsVoice, ttsStyle, setTtsStyle, ttsFormat, setTtsFormat, ttsSaving, ttsSaved, ttsError, saveTTS, voices };
}

function NutzerTab({ instance }: { instance: string }) {
  const { profile, isLoading, isSaving, error, saveSuccess, save } = useProfile(instance);
  const [displayName, setDisplayName] = useState("");
  const [language, setLanguage] = useState("de");
  const [githubUsername, setGithubUsername] = useState("");
  const [githubOrg, setGithubOrg] = useState("");
  const [customInstructions, setCustomInstructions] = useState("");
  const [mode, setMode] = useState<UserPreferences["permission_mode"]>("yolo");
  const [model, setModel] = useState<UserPreferences["model"]>("default");
  const [thinking, setThinking] = useState(false);
  const [maxTurns, setMaxTurns] = useState("20");
  const [budget, setBudget] = useState("");
  const [verbose, setVerbose] = useState<0 | 1 | 2>(1);
  const [workingDir, setWorkingDir] = useState("/root/workspace");
  const tts = useTTSSettings(instance);

  useEffect(() => {
    if (!profile) return;
    setDisplayName(profile.display_name ?? "");
    const p = profile.preferences;
    setLanguage(p.language ?? "de");
    setGithubUsername(p.github_username ?? "");
    setGithubOrg(p.github_org ?? "");
    setCustomInstructions(p.custom_instructions ?? "");
    setMode(p.permission_mode ?? "yolo");
    setModel(p.model ?? "default");
    setThinking(p.thinking ?? false);
    setMaxTurns(String(p.max_turns ?? 20));
    setBudget(p.budget != null ? String(p.budget) : "");
    setVerbose((p.verbose ?? 1) as 0 | 1 | 2);
    setWorkingDir(p.working_directory ?? "/root/workspace");
  }, [profile]);

  const handleSave = () => save({
    display_name: displayName || undefined, language,
    github_username: githubUsername || undefined, github_org: githubOrg || undefined,
    custom_instructions: customInstructions || undefined,
    permission_mode: mode, model, thinking,
    max_turns: parseInt(maxTurns) || 20,
    budget: budget ? parseFloat(budget) : null,
    verbose, working_directory: workingDir || "/root/workspace",
  });

  if (isLoading) return <div className="flex justify-center py-16"><Spinner /></div>;

  const Section = ({ title, children }: { title: string; children: React.ReactNode }) => (
    <div className="py-5 space-y-4" style={{ borderTop: "1px solid var(--border)" }}>
      <h3 className="text-[13px] font-medium" style={{ color: "var(--text-2)" }}>{title}</h3>
      {children}
    </div>
  );

  return (
    <div className="max-w-md space-y-0">
      <Section title="Profile">
        <Field label="Display name"><TextInput value={displayName} onChange={setDisplayName} placeholder="Your name" /></Field>
        <Field label="Language" hint="Language for bot responses">
          <SelectInput value={language} onChange={setLanguage} options={[
            { value: "de", label: "Deutsch" }, { value: "en", label: "English" },
            { value: "fr", label: "Français" }, { value: "es", label: "Español" },
          ]} />
        </Field>
      </Section>

      <Section title="GitHub">
        <Field label="Username"><TextInput value={githubUsername} onChange={setGithubUsername} placeholder="username" /></Field>
        <Field label="Organization"><TextInput value={githubOrg} onChange={setGithubOrg} placeholder="org-name" /></Field>
      </Section>

      <Section title="Custom Instructions">
        <textarea value={customInstructions} onChange={(e) => setCustomInstructions(e.target.value)} rows={4}
          placeholder="e.g. Always use TypeScript, follow Conventional Commits…"
          className={`${inputClass} resize-none`} style={inputStyle} />
      </Section>

      <Section title="Mode & Model">
        <Field label="Permission Mode" hint="yolo = unrestricted · approve = confirm before action · plan = read-only">
          <SelectInput value={mode} onChange={(v) => setMode(v as typeof mode)} options={[
            { value: "yolo", label: "yolo — Unrestricted (YOLO)" },
            { value: "approve", label: "approve — Require approval" },
            { value: "plan", label: "plan — Read only" },
          ]} />
        </Field>
        <Field label="Model">
          <SelectInput value={model} onChange={(v) => setModel(v as typeof model)} options={[
            { value: "default", label: "default (claude-sonnet-4-6)" },
            { value: "sonnet", label: "claude-sonnet-4-6" },
            { value: "opus", label: "claude-opus-4-6 (slow, powerful)" },
            { value: "haiku", label: "claude-haiku-4-5 (fast, cheap)" },
          ]} />
        </Field>
        <Toggle value={thinking} onChange={setThinking} label="Extended Thinking (increases latency & cost)" />
      </Section>

      <Section title="Limits">
        <div className="grid grid-cols-2 gap-4">
          <Field label="Max turns" hint="Per request"><TextInput value={maxTurns} onChange={setMaxTurns} placeholder="20" type="number" /></Field>
          <Field label="Budget (USD)" hint="Empty = unlimited"><TextInput value={budget} onChange={setBudget} placeholder="2.00" type="number" /></Field>
        </div>
      </Section>

      <Section title="Output & Directory">
        <Field label="Verbosity" hint="0 = quiet · 1 = compact · 2 = verbose">
          <SelectInput value={String(verbose)} onChange={(v) => setVerbose(parseInt(v) as 0|1|2)} options={[
            { value: "0", label: "0 — quiet" }, { value: "1", label: "1 — compact" }, { value: "2", label: "2 — verbose" },
          ]} />
        </Field>
        <Field label="Working directory">
          <TextInput value={workingDir} onChange={setWorkingDir} placeholder="/root/workspace" />
        </Field>
      </Section>

      <div className="pt-5 flex items-center gap-4" style={{ borderTop: "1px solid var(--border)" }}>
        <button onClick={handleSave} disabled={isSaving}
          className="flex items-center gap-2 px-4 py-2 rounded-md text-[13px] font-medium transition-colors disabled:opacity-40"
          style={{ backgroundColor: "var(--bg-muted)", color: "var(--text)", border: "1px solid var(--border)" }}>
          {isSaving ? <Spinner className="h-3.5 w-3.5" /> : null}
          {isSaving ? "Saving…" : "Save"}
        </button>
        {saveSuccess && <span className="text-[13px]" style={{ color: "var(--success)" }}>✓ Saved</span>}
        {error && <span className="text-[13px]" style={{ color: "var(--danger)" }}>{error}</span>}
      </div>

      {/* TTS Settings — separate save button */}
      <Section title="Text-to-Speech (TTS)">
        <Field label="Provider" hint="Gemini: more voices & style · OpenAI: natural sound">
          <SelectInput
            value={tts.ttsProvider}
            onChange={(v) => { tts.setTtsProvider(v); tts.setTtsVoice(v === "openai" ? "nova" : "Puck"); }}
            options={[
              { value: "gemini", label: "Gemini (Google)" },
              { value: "openai", label: "OpenAI" },
            ]}
          />
        </Field>
        <Field label="Voice">
          <SelectInput value={tts.ttsVoice} onChange={tts.setTtsVoice} options={tts.voices} />
        </Field>
        <Field label="Style prompt" hint='e.g. "speak slowly and warmly" — empty = no style'>
          <TextInput
            value={tts.ttsStyle}
            onChange={tts.setTtsStyle}
            placeholder="Empty = instance default"
          />
        </Field>
        <Field label="Output format">
          <SelectInput value={tts.ttsFormat} onChange={tts.setTtsFormat} options={[
            { value: "oga", label: "OGA / Opus (Standard)" },
            { value: "mp3", label: "MP3" },
            { value: "wav", label: "WAV" },
          ]} />
        </Field>
        <div className="flex items-center gap-4 pt-1">
          <button onClick={tts.saveTTS} disabled={tts.ttsSaving}
            className="flex items-center gap-2 px-4 py-2 rounded-md text-[13px] font-medium transition-colors disabled:opacity-40"
            style={{ backgroundColor: "var(--bg-muted)", color: "var(--text)", border: "1px solid var(--border)" }}>
            {tts.ttsSaving ? <Spinner className="h-3.5 w-3.5" /> : null}
            {tts.ttsSaving ? "Saving…" : "Save TTS"}
          </button>
          {tts.ttsSaved && <span className="text-[13px]" style={{ color: "var(--success)" }}>✓ Saved</span>}
          {tts.ttsError && <span className="text-[13px]" style={{ color: "var(--danger)" }}>{tts.ttsError}</span>}
        </div>
      </Section>

    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
// MAIN PAGE
// ══════════════════════════════════════════════════════════════════════════
type Tab = "stats" | "nutzer";

function SettingsContent() {
  const { instance } = useParams<{ instance: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const tab = (searchParams.get("tab") as Tab) ?? "stats";

  const setTab = (t: Tab) => router.replace(`/${instance}/settings?tab=${t}`);

  const tabs: { id: Tab; label: string }[] = [
    { id: "stats", label: "Statistics" },
    { id: "nutzer", label: "User" },
  ];

  return (
    <div className="flex-1 overflow-y-auto" style={{ backgroundColor: "var(--bg)" }}>
      <div className="max-w-3xl mx-auto px-6 py-8">
        {/* Header */}
        <div className="mb-6">
          <h1 className="text-[20px] font-semibold tracking-tight" style={{ color: "var(--text)" }}>Settings</h1>
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
                <span
                  className="absolute bottom-0 left-0 right-0 h-px"
                  style={{ backgroundColor: "var(--text)" }}
                />
              )}
            </button>
          ))}
        </div>

        {/* Tab content */}
        {tab === "stats" && <StatsTab instance={instance} />}
        {tab === "nutzer" && <NutzerTab instance={instance} />}
      </div>
    </div>
  );
}

export default function SettingsPage() {
  return (
    <Suspense fallback={<div className="flex items-center justify-center flex-1"><Spinner /></div>}>
      <SettingsContent />
    </Suspense>
  );
}
