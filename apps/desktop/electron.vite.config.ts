import { defineConfig } from "electron-vite";
import solid from "vite-plugin-solid";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const rootDir = resolve(__dirname, "../..");

const workspaceAliases = {
  "@applyocalypse/shared-types": resolve(rootDir, "packages/shared-types/src/index.ts"),
  "@applyocalypse/shared-schemas": resolve(rootDir, "packages/shared-schemas/src/index.ts"),
  "@applyocalypse/ipc-contracts": resolve(rootDir, "packages/ipc-contracts/src/index.ts"),
  "@applyocalypse/db": resolve(rootDir, "packages/db/src/index.ts"),
  "@applyocalypse/validator": resolve(rootDir, "packages/validator/src/index.ts"),
  "@applyocalypse/config": resolve(rootDir, "packages/config/src/index.ts"),
  "@applyocalypse/logging": resolve(rootDir, "packages/logging/src/index.ts"),
  "@applyocalypse/document-tools": resolve(rootDir, "packages/document-tools/src/index.ts"),
  "@applyocalypse/ui": resolve(rootDir, "packages/ui/src/index.ts")
};

export default defineConfig({
  main: {
    resolve: {
      alias: workspaceAliases
    },
    build: {
      rollupOptions: {
        input: {
          index: resolve(__dirname, "src/main/index.ts")
        },
        external: ["electron", "better-sqlite3"]
      }
    }
  },
  preload: {
    resolve: {
      alias: workspaceAliases
    },
    build: {
      rollupOptions: {
        input: {
          index: resolve(__dirname, "src/preload/index.ts")
        },
        external: ["electron"],
        output: {
          format: "cjs",
          entryFileNames: "[name].js"
        }
      }
    }
  },
  renderer: {
    root: resolve(__dirname),
    resolve: {
      alias: workspaceAliases
    },
    plugins: [solid()],
    build: {
      rollupOptions: {
        input: resolve(__dirname, "index.html")
      }
    }
  }
});
