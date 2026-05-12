#!/usr/bin/env node
// Sprint 9.5 B3 — bundle-size guardrail.
//
// Reads ``.next/app-build-manifest.json`` (Next 16 app-router layout)
// after ``next build`` and asserts that the per-route first-load JS
// stays under a budget. The discovery report flagged first-load at
// ~1.31 MB across 30 vendor chunks; the App-cluster routes target
// 350 KB. Numbers are uncompressed bytes — gzipped is ~30% smaller —
// kept liberal on first pass so this fails on regression, not on
// noise.
//
// Run locally: ``pnpm build && node scripts/check-bundle-size.mjs``.
// Wire into CI alongside the web build step once it exists. Exit 1 on
// budget violation, exit 0 otherwise. ``--report`` prints the table
// without enforcing budgets — useful for budget calibration after a
// deliberate dependency add.

import { readFile, stat } from "node:fs/promises";
import { join } from "node:path";
import process from "node:process";

const WEB_ROOT = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const BUILD_DIR = join(WEB_ROOT, ".next");
const MANIFEST = join(BUILD_DIR, "app-build-manifest.json");

// Route budget table — uncompressed bytes for the union of chunks a
// route loads on first paint. Keys match app-router page paths as
// emitted in app-build-manifest.json (e.g. "/(authenticated)/insights/page").
// Unlisted routes are checked against DEFAULT_BUDGET.
const DEFAULT_BUDGET = 400 * 1024;
const ROUTE_BUDGETS = {
  "/(authenticated)/insights/page": 380 * 1024,
  "/(authenticated)/strategy/page": 380 * 1024,
  "/(authenticated)/dashboard/page": 350 * 1024,
  "/(authenticated)/reviews/page": 350 * 1024,
  "/login/page": 250 * 1024,
};

const REPORT_ONLY = process.argv.includes("--report");

async function fileBytes(rel) {
  const s = await stat(join(BUILD_DIR, rel));
  return s.size;
}

async function main() {
  let manifest;
  try {
    manifest = JSON.parse(await readFile(MANIFEST, "utf8"));
  } catch (err) {
    console.error(
      `Could not read ${MANIFEST}. Did you run "pnpm build" first?\n${err.message}`,
    );
    process.exit(2);
  }

  const pages = manifest.pages ?? {};
  const rows = [];
  for (const [route, chunks] of Object.entries(pages)) {
    let total = 0;
    for (const chunk of chunks) {
      try {
        total += await fileBytes(chunk);
      } catch {
        // Stale entry in the manifest — skip; the build would have
        // failed if a real chunk were missing.
      }
    }
    const budget = ROUTE_BUDGETS[route] ?? DEFAULT_BUDGET;
    rows.push({ route, total, budget, over: total > budget });
  }
  rows.sort((a, b) => b.total - a.total);

  const fmt = (n) => `${(n / 1024).toFixed(1)} KB`;
  console.log("route                                                  size       budget    status");
  console.log("-".repeat(96));
  for (const r of rows) {
    const status = r.over ? "OVER" : "ok";
    const route = r.route.padEnd(54);
    console.log(
      `${route} ${fmt(r.total).padStart(10)} ${fmt(r.budget).padStart(10)}    ${status}`,
    );
  }

  const violations = rows.filter((r) => r.over);
  if (violations.length === 0) {
    console.log(`\nAll ${rows.length} routes within budget.`);
    return;
  }
  console.log(`\n${violations.length} route(s) over budget.`);
  if (REPORT_ONLY) {
    console.log("(--report mode: not failing the build)");
    return;
  }
  process.exit(1);
}

main().catch((err) => {
  console.error(err);
  process.exit(2);
});
