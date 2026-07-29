/**
 * Executes a JavaScript snippet produced by the Python worker against the DOM
 * stub in ./dom_stub.mjs.
 *
 * stdin:  {"spec": <dom spec>, "script": "<js source>"}
 * stdout: {"result": <return value of the snippet>, "state": [<field snapshots>]}
 */
import { buildDom } from "./dom_stub.mjs";

let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => {
  raw += chunk;
});
process.stdin.on("end", () => {
  try {
    const input = JSON.parse(raw);
    const env = buildDom(input.spec || {});
    const evaluate = new Function(
      "window",
      "document",
      "CSS",
      "Event",
      `return (${input.script});`
    );
    const result = evaluate(env.window, env.document, env.CSS, env.Event);
    process.stdout.write(JSON.stringify({ result, state: env.snapshot() }));
  } catch (error) {
    process.stdout.write(JSON.stringify({ error: String((error && error.stack) || error) }));
    process.exitCode = 1;
  }
});
