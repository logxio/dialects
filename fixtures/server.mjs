// Fixture HTTP server shared by the OpenClaw test suite.
//
// Serves the documents in fixtures/pages/ plus the routes that make a fetching
// tool fail: a redirect, a slow response, a 404, and a non-HTML body. Node
// built-ins only, binds an ephemeral port.

import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const PAGES = join(dirname(fileURLToPath(import.meta.url)), "pages");

// Bytes that no HTML parser should be asked to read.
const BINARY_BODY = Buffer.from("%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n");

const page = (name) => readFileSync(join(PAGES, name));

function send(res, status, body, contentType) {
  res.writeHead(status, { "Content-Type": contentType, "Content-Length": body.length });
  res.end(body);
}

/** Starts the fixture server on an ephemeral port. */
export async function startFixtureServer() {
  const server = createServer(async (req, res) => {
    const url = new URL(req.url ?? "/", "http://127.0.0.1");

    switch (url.pathname) {
      case "/article":
        return send(res, 200, page("article.html"), "text/html; charset=utf-8");
      case "/no-title":
        return send(res, 200, page("no-title.html"), "text/html; charset=utf-8");
      case "/redirect":
        res.writeHead(302, { Location: "/article", "Content-Length": 0 });
        return res.end();
      case "/slow": {
        const delayMs = Number(url.searchParams.get("ms") ?? 3000);
        await new Promise((resolve) => setTimeout(resolve, delayMs));
        return send(res, 200, page("article.html"), "text/html; charset=utf-8");
      }
      case "/not-found":
        return send(res, 404, Buffer.from("<html><body>gone</body></html>"), "text/html; charset=utf-8");
      case "/binary":
        return send(res, 200, BINARY_BODY, "application/pdf");
      default:
        return send(res, 404, Buffer.from("<html><body>no route</body></html>"), "text/html; charset=utf-8");
    }
  });

  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();

  return {
    baseUrl: `http://127.0.0.1:${port}`,
    async close() {
      server.closeAllConnections();
      await new Promise((resolve) => server.close(resolve));
    },
  };
}
