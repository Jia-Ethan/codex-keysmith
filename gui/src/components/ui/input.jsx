import * as React from "react";
import { cn } from "@/lib/utils";

function Input({ className, type, ...props }) {
  return (
    <input
      type={type}
      className={cn(
        "flex h-9 w-full rounded-[10px] border border-border bg-background px-3 py-1 text-sm text-foreground",
        "placeholder:text-muted-foreground",
        "focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-1 focus-visible:border-accent",
        "disabled:cursor-not-allowed disabled:opacity-50",
        "transition-colors duration-200",
        className,
      )}
      {...props}
    />
  );
}

export { Input };
