/**
 * Publish a run directory to Vercel Blob under the stable `wrf/` prefix.
 *
 *   node wrf/scripts/publish.mts <run-dir> [--only <file>]
 *
 * Uploads every top-level *.json artifact (map-field.json, cross-section-*.json,
 * run.json) with fixed paths, overwriting the previous cycle; run.json goes
 * LAST so a reader never sees a new stamp pointing at old data. `--only` is the
 * failure path: publish a single run.json and nothing else.
 *
 * The read-write token comes from wrf/.env (BLOB_READ_WRITE_TOKEN) and is never
 * printed.
 */
import { put } from "@vercel/blob";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

const [runDirArg, ...rest] = process.argv.slice(2);
if (!runDirArg) {
  console.error("usage: publish.mts <run-dir> [--only <file>]");
  process.exit(2);
}
const onlyIdx = rest.indexOf("--only");
const only = onlyIdx >= 0 ? rest[onlyIdx + 1] : null;

try {
  process.loadEnvFile(path.join(import.meta.dirname, "..", ".env"));
} catch {
  console.error("wrf/.env not found — put BLOB_READ_WRITE_TOKEN there first");
  process.exit(1);
}
if (!process.env.BLOB_READ_WRITE_TOKEN) {
  console.error("BLOB_READ_WRITE_TOKEN is not set in wrf/.env");
  process.exit(1);
}

const runDir = path.resolve(runDirArg);
let names = (await readdir(runDir, { withFileTypes: true }))
  .filter((entry) => entry.isFile() && entry.name.endsWith(".json"))
  .map((entry) => entry.name)
  .sort((a, b) => a.localeCompare(b));
if (only) {
  names = names.filter((name) => name === only);
}
if (names.length === 0) {
  console.error(`no JSON artifacts to publish in ${runDir}${only ? ` (looking for ${only})` : ""}`);
  process.exit(1);
}
// run.json LAST: the stamp a reader trusts must never precede its data.
names.sort((a, b) => Number(a === "run.json") - Number(b === "run.json") || a.localeCompare(b));

let baseUrl: string | null = null;
for (const name of names) {
  const body = await readFile(path.join(runDir, name));
  const blob = await put(`wrf/${name}`, body, {
    access: "public",
    addRandomSuffix: false,
    allowOverwrite: true,
    cacheControlMaxAge: 300,
    contentType: "application/json",
  });
  if (!baseUrl) {
    baseUrl = blob.url.slice(0, blob.url.lastIndexOf("/") + 1);
  }
  console.log(`published ${blob.url}  (${body.length} B)`);
}
console.log(`base URL: ${baseUrl}`);
