import React from "react";
import { useTranslation } from "react-i18next";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogAction,
  AlertDialogCancel,
} from "@/components/ui/alert-dialog";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * 受控确认对话框（危险操作用 destructive 变体）
 * props: open, onOpenChange, title, body, confirmText, confirmDisabled, danger, onConfirm
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  body,
  confirmText,
  confirmDisabled = false,
  danger,
  onConfirm,
}) {
  const { t } = useTranslation();
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogTitle>{title}</AlertDialogTitle>
        {body ? <AlertDialogDescription>{body}</AlertDialogDescription> : null}
        <div className="mt-5 flex justify-end gap-2">
          <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
          <AlertDialogAction
            className={cn(danger && buttonVariants({ variant: "destructive" }))}
            disabled={confirmDisabled}
            onClick={onConfirm}
          >
            {confirmText || t("common.confirm")}
          </AlertDialogAction>
        </div>
      </AlertDialogContent>
    </AlertDialog>
  );
}
