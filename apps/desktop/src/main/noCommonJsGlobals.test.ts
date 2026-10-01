import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const mainDir = dirname(fileURLToPath(import.meta.url));

const sourceFiles = (dir: string): string[] =>
  readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.ts$/.test(name) && !/\.test\.ts$/.test(name) ? [path] : [];
  });

const COMMONJS_GLOBAL = /(?<![\w$.])(__dirname|__filename|require\()/;

/**
 * The main bundle is an ES module. electron-vite only provides __dirname,
 * __filename and require through a shim it pastes after the last `import`
 * line it finds, and a bundled dependency with an example import inside a doc
 * comment swallows that shim: the app then dies at startup with
 * "__dirname is not defined". Main-process code derives paths from
 * import.meta.url instead.
 */
describe("main process code", () => {
  it("does not lean on the CommonJS globals", () => {
    const offenders = sourceFiles(mainDir).flatMap((file) =>
      readFileSync(file, "utf8")
        .split("\n")
        .map((line, index) => ({ line: line.trim(), number: index + 1 }))
        .filter(({ line }) => !line.startsWith("//") && !line.startsWith("*") && COMMONJS_GLOBAL.test(line))
        .map(({ line, number }) => `${relative(mainDir, file)}:${number}: ${line}`)
    );
    expect(offenders).toEqual([]);
  });
});
