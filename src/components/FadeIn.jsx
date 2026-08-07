import React from "react";
import { motion, useReducedMotion } from "motion/react";

/** 入场动效：reduced-motion 下只做短淡入（保留功能性反馈，去掉位移） */
export function FadeIn({ delay = 0, children, className, ...props }) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: reduce ? 0 : 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: reduce ? 0.15 : 0.5,
        delay,
        ease: [0.22, 1, 0.36, 1],
      }}
      {...props}
    >
      {children}
    </motion.div>
  );
}
