import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-[10px] text-sm font-medium transition-all duration-200 cursor-pointer disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0 focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2",
  {
    variants: {
      variant: {
        default:
          "bg-accent text-white btn-glow hover:bg-accent-hover",
        destructive:
          "bg-danger text-white hover:opacity-90 dark:hover:shadow-[0_0_20px_var(--danger-soft)]",
        outline:
          "border border-border bg-transparent text-foreground hover:bg-elevated hover:border-border-hover",
        secondary:
          "bg-elevated text-foreground hover:bg-border",
        ghost:
          "text-secondary-foreground hover:bg-elevated hover:text-foreground",
        warning:
          "bg-warn text-white hover:opacity-90",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-7 rounded-[8px] px-2.5 text-xs",
        lg: "h-11 rounded-[12px] px-6 text-base",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

function Button({ className, variant, size, asChild = false, ...props }) {
  const Comp = asChild ? Slot : "button";
  return (
    <Comp
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  );
}

export { Button, buttonVariants };
