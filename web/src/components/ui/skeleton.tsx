import { cn } from "@/lib/utils";

/**
 * Loading placeholder. Compose by sizing via className, e.g.
 * `<Skeleton className="h-4 w-32" />`.
 */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      className={cn("animate-pulse rounded-md bg-muted", className)}
      {...props}
    />
  );
}

export { Skeleton };
