import * as React from "react";
import * as AlertDialogPrimitive from "@radix-ui/react-alert-dialog";
import { cn } from "@/lib/utils";
import { buttonVariants } from "./button";

const AlertDialog = AlertDialogPrimitive.Root;
const AlertDialogTrigger = AlertDialogPrimitive.Trigger;

function AlertDialogContent({ className, ...props }) {
  return (
    <AlertDialogPrimitive.Portal>
      <AlertDialogPrimitive.Overlay
        className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm data-[state=open]:animate-in data-[state=open]:fade-in-0"
      />
      <AlertDialogPrimitive.Content
        className={cn(
          "card-glass fixed left-1/2 top-1/2 z-50 w-[min(440px,90vw)] -translate-x-1/2 -translate-y-1/2 p-6",
          "focus:outline-none",
          className,
        )}
        {...props}
      />
    </AlertDialogPrimitive.Portal>
  );
}

function AlertDialogTitle({ className, ...props }) {
  return (
    <AlertDialogPrimitive.Title
      className={cn("text-base font-semibold text-foreground", className)}
      {...props}
    />
  );
}

function AlertDialogDescription({ className, ...props }) {
  return (
    <AlertDialogPrimitive.Description
      className={cn("mt-2 text-sm text-secondary-foreground break-all", className)}
      {...props}
    />
  );
}

function AlertDialogAction({ className, ...props }) {
  return (
    <AlertDialogPrimitive.Action
      className={cn(buttonVariants(), className)}
      {...props}
    />
  );
}

function AlertDialogCancel({ className, ...props }) {
  return (
    <AlertDialogPrimitive.Cancel
      className={cn(buttonVariants({ variant: "outline" }), className)}
      {...props}
    />
  );
}

export {
  AlertDialog,
  AlertDialogTrigger,
  AlertDialogContent,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogAction,
  AlertDialogCancel,
};
