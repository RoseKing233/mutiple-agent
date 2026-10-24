import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { cn } from "@/lib/utils";
import type { AgentMeta } from "@/lib/agents";

interface AgentHeroProps {
  agent: AgentMeta;
}

export function AgentHero({ agent }: AgentHeroProps) {
  const Icon = agent.icon;
  return (
    <div>
      <Link
        href="/agents"
        className="mb-6 inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" />
        All agents
      </Link>

      <div className="flex items-start gap-5">
        <div
          className={cn(
            "flex size-16 shrink-0 items-center justify-center rounded-2xl",
            agent.accentBg,
          )}
        >
          <Icon className={cn("size-8", agent.accentText)} aria-hidden />
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-bold tracking-tight">{agent.name}</h1>
            <span
              className={cn(
                "rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset",
                agent.accentText,
                agent.accentBg,
                "ring-current/20",
              )}
            >
              {agent.role}
            </span>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{agent.tagline}</p>
        </div>
      </div>

      <p className="mt-5 max-w-3xl text-sm leading-relaxed text-foreground/80">
        {agent.description}
      </p>
    </div>
  );
}
