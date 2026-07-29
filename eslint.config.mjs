import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";
import solid from "eslint-plugin-solid/configs/typescript";

export default tseslint.config(
  {
    ignores: [
      "**/dist/**",
      "**/out/**",
      "**/release/**",
      "**/node_modules/**",
      "plans/**",
      ".claude/**",
      ".tmp-electron-rebuild/**",
      "services/automation-python/**",
      "**/*.config.{js,mjs,ts}"
    ]
  },
  {
    files: [
      "packages/**/src/**/*.ts",
      "apps/desktop/src/**/*.{ts,tsx}",
      "scripts/**/*.ts",
      "tests/**/*.ts"
    ],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      globals: { ...globals.node, ...globals.browser }
    },
    rules: {
      eqeqeq: ["error", "always", { null: "ignore" }],
      "no-var": "error"
    }
  },
  {
    files: ["scripts/**/*.mjs"],
    extends: [js.configs.recommended],
    languageOptions: {
      sourceType: "module",
      globals: { ...globals.node }
    },
    rules: {
      eqeqeq: ["error", "always", { null: "ignore" }],
      "no-var": "error"
    }
  },
  {
    files: ["**/*.test.ts"],
    rules: {
      "@typescript-eslint/no-explicit-any": "off"
    }
  },
  {
    files: ["apps/desktop/src/**/*.tsx"],
    extends: [solid],
    rules: {
      // Converting Array#map -> <For> is a real refactor; track as follow-up debt.
      "solid/prefer-for": "warn"
    }
  }
);
