/**
 * Resolve the WRF grid contract into a JSON file the post-process reads.
 *
 * Order: sibling checkout (../mtwashingtonsoaring/public/wrf-contract.json) →
 * the deployed site (https://mtwashingtonsoaring.org/wrf-contract.json) → fail
 * loudly. The contract is generated from the site's src/lib/wx-grid.ts, so the
 * model grid and pressure levels cannot drift from what the views read.
 *
 *   node wrf/scripts/export-grid.mts [--out PATH] [--site PATH] [--url URL]
 */
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const args = process.argv.slice(2);
const flag = (name: string, fallback: string): string => {
  const index = args.indexOf(name);
  return index >= 0 && args[index + 1] ? args[index + 1] : fallback;
};

const out = path.resolve(flag("--out", path.join(import.meta.dirname, "..", "out", "grid.json")));
const site = path.resolve(
  flag(
    "--site",
    path.join(import.meta.dirname, "..", "..", "..", "mtwashingtonsoaring", "public", "wrf-contract.json"),
  ),
);
const url = flag("--url", "https://mtwashingtonsoaring.org/wrf-contract.json");

async function load(): Promise<{ text: string; source: string }> {
  try {
    return { text: await readFile(site, "utf8"), source: site };
  } catch {
    const response = await fetch(url, { signal: AbortSignal.timeout(15_000) });
    if (!response.ok) {
      throw new Error(`contract missing at ${site} and ${url} returned HTTP ${response.status}`);
    }
    return { text: await response.text(), source: url };
  }
}

const { text, source } = await load();
const contract = JSON.parse(text) as { schema?: number; map_points?: unknown[] };
if (contract.schema !== 1 || !Array.isArray(contract.map_points) || contract.map_points.length !== 247) {
  console.error("contract failed validation (schema must be 1, map_points must hold 247 entries)");
  process.exit(1);
}
await mkdir(path.dirname(out), { recursive: true });
await writeFile(out, JSON.stringify(contract));
console.log(`grid contract from ${source} -> ${out} (${contract.map_points.length} points)`);
