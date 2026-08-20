// Print the parse result at several truncation points, for cross-language diffing.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { parseHtml } from "../openclaw/dist/core.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const CUTS = [100, 150, 200, 300, 400, 552];

const raw = readFileSync(join(ROOT, "fixtures", "pages", "article.html"));
for (const cut of CUTS) {
  const page = parseHtml(new TextDecoder("utf-8").decode(raw.subarray(0, cut)));
  process.stdout.write(`${cut}\t${page.title}\t${page.wordCount}\n`);
}
