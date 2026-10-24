"use client";

import { Activity, Zap, Layers } from "lucide-react";
import { StatCard } from "@/components/ui/stat-card";

interface AgentStat {
  agent_name: string;
  request_count: number;
  avg_duration_ms: number;
  total_tokens: number;
}

interface AgentStatsStripProps {
  backendName: string;
  stats: AgentStat[] | null;
}

function formatDuration(ms: number): string {
  if (ms === 0) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatTokens(n: number): string {
  if (n === 0) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}k`;
  return String(n);
}

export function AgentStatsStrip({ backendName, stats }: AgentStatsStripProps) {
  const row = stats?.find((s) => s.agent_name === backendName);

  const invocations = row?.request_count ?? 0;
  const avgMs = row?.avg_duration_ms ?? 0;
  const tokens = row?.total_tokens ?? 0;

  return (
    <section>
      <h2 className="mb-3 text-sm font-semibold text-foreground">
        Last 30 days
      </h2>
      <div className="grid gap-3 sm:grid-cols-3">
        <StatCard
          label="Invocations"
          value={invocations === 0 && stats !== null ? "0" : invocations === 0 ? "—" : invocations.toLocaleString()}
          icon={Activity}
          hint="total requests"
        />
        <StatCard
          label="Avg latency"
          value={formatDuration(avgMs)}
          icon={Zap}
          hint="end-to-end"
        />
        <StatCard
          label="Tokens used"
          value={formatTokens(tokens)}
          icon={Layers}
          hint="in + out"
        />
      </div>
    </section>
  );
}
