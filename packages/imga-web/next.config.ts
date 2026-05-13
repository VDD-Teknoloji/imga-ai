import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // standalone output keeps the production Docker image small —
  // the runner stage copies only .next/standalone + .next/static
  // + public/.
  output: "standalone",
  reactStrictMode: true,

  // Sprint 9.5 B3 — bundle slimming. ``optimizePackageImports`` tells
  // Next 16 to barrel-strip the listed packages so only the named
  // imports actually used survive into the bundle. Big win for
  // lucide-react (~200 KB → ~20 KB on a typical page); recharts /
  // base-ui / dnd-kit are smaller but still worth shaking.
  //
  // Sprint 9.5.3 — the original B3 also wired ``modularizeImports``
  // for lucide-react as a "belt-and-suspenders" compile-time
  // transform. That broke the build. lucide-react's exports are
  // named ``CheckIcon`` / ``WandIcon`` / etc. but the underlying
  // file is ``check.mjs`` / ``wand.mjs`` — no ``-icon`` suffix. The
  // naive ``{{kebabCase member}}`` transform produced ``check-icon``
  // → 14 "Module not found" errors on a clean ``next build``. The
  // server-agent's uncommitted next.config.ts patch had been
  // masking this in production by removing the block before each
  // rebuild. Dropped here permanently; optimizePackageImports does
  // the tree-shake without needing the transform.
  //
  // Route-level dynamic() splits land in code (insights tabs) — see
  // the relevant page.tsx files.
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
};

export default nextConfig;
