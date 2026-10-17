import { cn } from "@/lib/utils";

export function Logo({ className, withText = true }: { className?: string; withText?: boolean }) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <div className="relative flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-accent to-accent-2 shadow-[0_0_24px_-4px_rgb(var(--accent)/0.7)]">
        <svg viewBox="0 0 24 24" className="h-4 w-4 text-white" fill="none" stroke="currentColor" strokeWidth={2.4}>
          <ellipse cx="12" cy="6" rx="7" ry="2.6" />
          <path d="M5 6v6c0 1.4 3.1 2.6 7 2.6" />
          <path d="M5 12v6c0 1.4 3.1 2.6 7 2.6" />
          <path d="m15 15 2.5 2.5L22 13" />
        </svg>
      </div>
      {withText && <span className="text-[15px] font-semibold tracking-tight">QueryPilot</span>}
    </div>
  );
}
