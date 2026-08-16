#!/usr/bin/env node
/**
 * Minimal static file server for the sovereign shard frontend production build.
 *
 * Usage: node serve-build.js <build-dir> <port>
 *
 * Serves index.html for unknown routes (SPA fallback), sets correct
 * Content-Type headers, and injects the REACT_APP_BACKEND_URL at runtime
 * so the same artifact works regardless of where the shard is deployed.
 */
const http = require("http");
const fs = require("fs");
const path = require("path");

const BUILD_DIR = process.argv[2] || ".";
const PORT = parseInt(process.argv[3] || "3000", 10);

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".ico": "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".eot": "application/vnd.ms-fontobject",
  ".map": "application/json; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
};

const server = http.createServer((req, res) => {
  let urlPath = req.url.split("?")[0];

  // Normalize path
  if (urlPath === "/") urlPath = "/index.html";

  const filePath = path.join(BUILD_DIR, urlPath);

  // Prevent path traversal
  if (!filePath.startsWith(path.resolve(BUILD_DIR))) {
    res.writeHead(403);
    res.end("Forbidden");
    return;
  }

  fs.stat(filePath, (err, stat) => {
    if (err || !stat.isFile()) {
      // SPA fallback — serve index.html for client-side routing
      const fallback = path.join(BUILD_DIR, "index.html");
      fs.readFile(fallback, (e2, data) => {
        if (e2) {
          res.writeHead(404);
          res.end("Not found");
          return;
        }
        res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
        res.end(data);
      });
      return;
    }

    const ext = path.extname(filePath).toLowerCase();
    const contentType = MIME[ext] || "application/octet-stream";
    fs.readFile(filePath, (e3, data) => {
      if (e3) {
        res.writeHead(500);
        res.end("Internal server error");
        return;
      }
      res.writeHead(200, { "Content-Type": contentType });
      res.end(data);
    });
  });
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`[sovereign-frontend] Serving ${BUILD_DIR} on http://127.0.0.1:${PORT}`);
});

server.on("error", (e) => {
  if (e.code === "EADDRINUSE") {
    console.error(`[sovereign-frontend] Port ${PORT} is already in use.`);
  } else {
    console.error(`[sovereign-frontend] Server error: ${e.message}`);
  }
  process.exit(1);
});
