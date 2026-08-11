import React from "react";
import { useTranslation } from "react-i18next";
import {
  LayoutDashboard,
  Rocket,
  Wrench,
  Settings,
  KeyRound,
  ChevronsLeft,
  ChevronsRight,
} from "lucide-react";
import { motion } from "motion/react";
import { cn } from "@/lib/utils";
import { useAppState } from "@/hooks/useAppState";
import { setView } from "@/lib/store";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

const NAV = [
  { key: "dashboard", icon: LayoutDashboard },
  { key: "deploy", icon: Rocket },
  { key: "manage", icon: Wrench },
  { key: "settings", icon: Settings },
];

/**
 * 侧边栏：hover 或键盘 focus-within 展开（可访问性修复：
 * 原先只绑 hover，键盘用户展不开）。motion 做宽度动画。
 */
export function Sidebar() {
  const { t } = useTranslation();
  const { view, operationInProgress } = useAppState();
  const [pinned, setPinned] = React.useState(false);

  return (
    <motion.nav
      aria-label={t("nav.subtitle")}
      className={cn(
        "group/sidebar relative z-10 flex h-full flex-col border-r border-border",
        "bg-[color-mix(in_srgb,var(--bg-secondary)_72%,transparent)] backdrop-blur-xl",
      )}
      initial={false}
      animate={{ width: pinned ? 200 : 56 }}
      whileHover={{ width: 200 }}
      onFocusCapture={() => setPinned(true)}
      onBlurCapture={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget)) setPinned(false);
      }}
      transition={{ type: "spring", stiffness: 380, damping: 34 }}
      style={{ minWidth: 56 }}
    >
      {/* 品牌 */}
      <div className="flex h-14 items-center gap-2.5 border-b border-border px-[15px]">
        <KeyRound className="size-5 shrink-0 text-accent" aria-hidden="true" />
        <div className="overflow-hidden whitespace-nowrap opacity-0 transition-opacity duration-200 group-hover/sidebar:opacity-100 group-focus-within/sidebar:opacity-100">
          <div className="text-sm font-semibold leading-tight">keysmith</div>
          <div className="text-[10px] text-muted-foreground leading-tight">
            {t("nav.subtitle")}
          </div>
        </div>
      </div>

      {/* 导航项 */}
      <TooltipProvider delayDuration={200}>
        <div className="flex flex-1 flex-col gap-1 p-2">
          {NAV.map(({ key, icon: Icon }) => {
            const active = view === key;
            const item = (
              <button
                key={key}
                data-view={key}
                aria-current={active ? "page" : undefined}
                disabled={operationInProgress}
                onClick={() => setView(key)}
                className={cn(
                  "relative flex h-10 items-center gap-2.5 rounded-[10px] px-[11px] text-sm transition-colors cursor-pointer",
                  "disabled:cursor-not-allowed disabled:opacity-50",
                  active
                    ? "text-accent font-medium"
                    : "text-secondary-foreground hover:text-foreground hover:bg-elevated",
                )}
              >
                {active && (
                  <motion.span
                    layoutId="nav-active"
                    className="absolute inset-0 rounded-[10px] bg-accent-soft"
                    transition={{ type: "spring", stiffness: 420, damping: 32 }}
                  />
                )}
                <Icon className="relative z-10 size-[18px] shrink-0" aria-hidden="true" />
                <span className="relative z-10 nav-label overflow-hidden whitespace-nowrap opacity-0 transition-opacity duration-200 group-hover/sidebar:opacity-100 group-focus-within/sidebar:opacity-100">
                  {t(`nav.${key}`)}
                </span>
              </button>
            );
            return (
              <Tooltip key={key}>
                <TooltipTrigger asChild>{item}</TooltipTrigger>
                <TooltipContent side="right">{t(`nav.${key}`)}</TooltipContent>
              </Tooltip>
            );
          })}
        </div>
      </TooltipProvider>

      {/* 收起/展开（键盘可达的显式开关） */}
      <div className="border-t border-border p-2">
        <button
          onClick={() => setPinned((v) => !v)}
          aria-label={pinned ? t("nav.collapse") : t("nav.expand")}
          aria-expanded={pinned}
          className="flex h-9 w-full items-center gap-2.5 rounded-[10px] px-[11px] text-muted-foreground transition-colors cursor-pointer hover:bg-elevated hover:text-foreground"
        >
          {pinned ? (
            <ChevronsLeft className="size-[18px] shrink-0" aria-hidden="true" />
          ) : (
            <ChevronsRight className="size-[18px] shrink-0" aria-hidden="true" />
          )}
          <span className="overflow-hidden whitespace-nowrap text-xs opacity-0 transition-opacity duration-200 group-hover/sidebar:opacity-100 group-focus-within/sidebar:opacity-100">
            {pinned ? t("nav.collapse") : t("nav.expand")}
          </span>
        </button>
      </div>
    </motion.nav>
  );
}
