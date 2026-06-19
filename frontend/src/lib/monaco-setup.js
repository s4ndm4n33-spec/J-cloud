/**
 * Monaco editor — self-hosted, bundled with the app.
 *
 * Why this file exists:
 *   `@monaco-editor/react` defaults to fetching the entire Monaco runtime
 *   from `https://cdn.jsdelivr.net/...` at first paint. That works on most
 *   networks, but on locked-down corporate networks, strict CSPs, or when
 *   jsdelivr is rate-limiting, the editor never finishes loading and the
 *   IDE is unusable. This module forces Monaco to use the locally bundled
 *   copy from `node_modules/monaco-editor`, which Webpack 5 (CRA 5) bundles
 *   into the app's own asset chunks via `new URL(..., import.meta.url)`.
 *
 * Import this module ONCE at app startup (in App.js) before any Monaco UI
 * mounts. Idempotent — safe to import multiple times.
 */
import { loader } from "@monaco-editor/react";
import * as monaco from "monaco-editor";

// Tell Monaco where its worker scripts live. Webpack 5 turns each
// `new URL(...)` into a bundled asset URL pointing at our own origin.
self.MonacoEnvironment = {
  getWorker(_, label) {
    if (label === "json") {
      return new Worker(
        new URL("monaco-editor/esm/vs/language/json/json.worker.js", import.meta.url),
        { type: "module" }
      );
    }
    if (label === "css" || label === "scss" || label === "less") {
      return new Worker(
        new URL("monaco-editor/esm/vs/language/css/css.worker.js", import.meta.url),
        { type: "module" }
      );
    }
    if (label === "html" || label === "handlebars" || label === "razor") {
      return new Worker(
        new URL("monaco-editor/esm/vs/language/html/html.worker.js", import.meta.url),
        { type: "module" }
      );
    }
    if (label === "typescript" || label === "javascript") {
      return new Worker(
        new URL("monaco-editor/esm/vs/language/typescript/ts.worker.js", import.meta.url),
        { type: "module" }
      );
    }
    return new Worker(
      new URL("monaco-editor/esm/vs/editor/editor.worker.js", import.meta.url),
      { type: "module" }
    );
  },
};

// Make `@monaco-editor/react` use the bundled monaco instead of the CDN copy.
loader.config({ monaco });

// Optional: kick off the initial load eagerly so the editor is ready the
// moment the user opens a file (vs. lazy-loaded on first mount).
loader.init();
