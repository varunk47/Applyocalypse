import { defineConfig } from "vitest/config";
import { resolve } from "node:path";

export default defineConfig({
  resolve: {
    alias: {
      "@applyocalypse/shared-types": resolve(__dirname, "packages/shared-types/src/index.ts"),
      "@applyocalypse/shared-schemas": resolve(__dirname, "packages/shared-schemas/src/index.ts"),
      "@applyocalypse/ipc-contracts": resolve(__dirname, "packages/ipc-contracts/src/index.ts"),
      "@applyocalypse/db": resolve(__dirname, "packages/db/src/index.ts"),
      "@applyocalypse/validator": resolve(__dirname, "packages/validator/src/index.ts"),
      "@applyocalypse/config": resolve(__dirname, "packages/config/src/index.ts"),
      "@applyocalypse/logging": resolve(__dirname, "packages/logging/src/index.ts"),
      "@applyocalypse/document-tools": resolve(__dirname, "packages/document-tools/src/index.ts"),
      "@applyocalypse/ui": resolve(__dirname, "packages/ui/src/index.ts")
    }
  },
  test: {
    globals: false,
    environment: "node",
    include: ["packages/**/*.test.ts", "apps/**/*.test.ts", "tests/**/*.test.ts"],
    coverage: {
      provider: "v8",
      reporter: ["text", "json-summary"],
      // Scope to source only — built bundles (out/, assets/) and configs are not meaningful to cover.
      include: ["packages/*/src/**/*.ts", "apps/desktop/src/**/*.{ts,tsx}"],
      exclude: ["**/*.test.ts", "**/*.d.ts"],
      // Floors set ~5pts below measured actuals (catch regressions, not aspirational).
      // Ratchet upward as renderer-screen tests land (see plan 017). Measured 2026-06:
      // lines/statements 42.7%, branches 68.9%, functions 67.3%.
      thresholds: {
        branches: 63,
        functions: 62,
        lines: 37,
        statements: 37
      }
    }
  }
});
