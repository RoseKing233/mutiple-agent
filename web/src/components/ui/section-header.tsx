import { cn } from "@/lib/utils";

export interface SectionHeaderProps {
  title: string;
  description?: string;
  /** Small uppercase label above the title. */
  eyebrow?: string;
  /** Right-aligned slot, e.g. a button or filter. */
  action?: React.ReactNode;
  className?: string;
}

/** Consistent header for page/section blocks across the app shell. */
export function SectionHeader({
  title,
  description,
  eyebrow,
  action,
  className,
}: SectionHeaderProps) {
  return (
    <div className={cn("mb-4 flex items-start justify-between gap-4", className)}>
      <div className="space-y-1">
        {eyebrow && (
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            {eyebrow}
          </p>
        )}
        <h2 className="font-heading text-lg font-semibold tracking-tight">
          {title}
        </h2>
        {description && (
          <p className="text-sm text-muted-foreground">{description}</p>
        )}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}
