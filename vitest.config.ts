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
      thresholds: {
        branches: 80,
        functions: 80,
        lines: 80,
        statements: 80
      }
    }
  }
});
