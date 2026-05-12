import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // standalone output keeps the production Docker image small —
  // the runner stage copies only .next/standalone + .next/static
  // + public/.
  output: "standalone",
  reactStrictMode: true,

  // Sprint 9.5 B3 — bundle slimming. Discovery report flagged
  // first-load JS at ~1.31 MB uncompressed across 30 vendor
  // chunks (lucide-react ~200 KB by itself, recharts loaded
  // eagerly on routes that don't actually chart). The fixes:
  //
  //   1. ``optimizePackageImports`` tells Next to barrel-strip the
  //      listed packages — only the specific named imports you
  //      use survive into the bundle. Massive win for
  //      lucide-react (~200 KB → ~20 KB on a typical page) and
  //      lower wins for the rest.
  //
  //   2. ``modularizeImports`` for lucide-react is the belt-and-
  //      suspenders compile-time transform: even on legacy Next
  //      versions or edge runtimes where optimizePackageImports
  //      hasn't fully kicked in, the per-icon path keeps tree-
  //      shaking honest.
  //
  // Route-level dynamic() splits land in code (insights tabs,
  // strategy PDF flow) — see the relevant page.tsx files.
  experimental: {
    optimizePackageImports: [
      "lucide-react",
      "recharts",
      "@base-ui/react",
      "@dnd-kit/core",
      "@dnd-kit/sortable",
      "@dnd-kit/utilities",
    ],
  },
  modularizeImports: {
    "lucide-react": {
      transform: "lucide-react/dist/esm/icons/{{kebabCase member}}",
      preventFullImport: true,
    },
  },
};

export default nextConfig;
