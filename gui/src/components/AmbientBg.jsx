import React from "react";

/** 全站环境背景层：三团主题色光晕缓慢漂移（reduced-motion 下静止，见 globals.css） */
export function AmbientBg() {
  return (
    <div className="ambient-bg" aria-hidden="true">
      <div className="ambient-glow ambient-glow-1" />
      <div className="ambient-glow ambient-glow-2" />
      <div className="ambient-glow ambient-glow-3" />
    </div>
  );
}
