"use client";

import { ResponsiveContainer } from "recharts";
import { cn } from "@/lib/utils";

/**
 * Chart color tokens, wired to the OKLCH `--chart-*` CSS variables in
 * globals.css so charts adapt to light/dark automatically. Use by index.
 */
export const CHART_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
] as const;

export interface ChartContainerProps {
  /** A single recharts chart element (e.g. <LineChart>...</LineChart>). */
  children: React.ReactElement;
  /** Fixed pixel height; width is always responsive. */
  height?: number;
  className?: string;
}

/**
 * Responsive wrapper around recharts. Keeps a fixed height (recharts needs a
 * bounded box) while the width fills the parent.
 */
export function ChartContainer({
  children,
  height = 240,
  className,
}: ChartContainerProps) {
  return (
    <div
      data-slot="chart"
      className={cn("w-full", className)}
      style={{ height }}
    >
      <ResponsiveContainer width="100%" height="100%">
        {children}
      </ResponsiveContainer>
    </div>
  );
}
