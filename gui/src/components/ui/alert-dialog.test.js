import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const dialogSource = readFileSync(new URL("./alert-dialog.jsx", import.meta.url), "utf8");
const globalsCss = readFileSync(new URL("../../globals.css", import.meta.url), "utf8");

function classRuleBodies(className) {
  const exactClass = new RegExp(`(?:^|[^-\\w])\\.${className}(?![-\\w])`);
  return [...globalsCss.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
    .filter(([, selectors]) => exactClass.test(selectors))
    .map(([, selectors, body]) => ({ selectors: selectors.trim(), body }));
}

describe("AlertDialog layout contract", () => {
  it("keeps the shared glass surface layout-neutral", () => {
    const rules = classRuleBodies("card-glass");

    expect(rules.length).toBeGreaterThan(0);
    for (const rule of rules) {
      expect(rule.body, rule.selectors).not.toMatch(/\bposition\s*:/);
    }
  });

  it("keeps blur on the overlay and fixed positioning on the dialog", () => {
    expect(dialogSource).toMatch(
      /AlertDialogPrimitive\.Overlay[\s\S]*className="[^"]*\bfixed\b[^"]*\bbackdrop-blur-sm\b[^"]*"/,
    );
    expect(dialogSource).toMatch(
      /AlertDialogPrimitive\.Content[\s\S]*"[^"]*\bcard-glass\b[^"]*\bfixed\b[^"]*"/,
    );
  });
});
