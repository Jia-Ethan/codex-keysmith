import * as React from "react";
import { cva } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
  {
    variants: {
      variant: {
        default: "border-transparent bg-elevated text-secondary-foreground",
        green: "border-transparent bg-[var(--ok-soft)] text-ok",
        yellow: "border-transparent bg-[var(--warn-soft)] text-warn",
        red: "border-transparent bg-[var(--danger-soft)] text-danger",
        gray: "border-transparent bg-elevated text-muted-foreground",
        accent: "border-transparent bg-accent-soft text-accent",
        outline: "border-border text-secondary-foreground",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

function Badge({ className, variant, ...props }) {
  return (
    <span className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
