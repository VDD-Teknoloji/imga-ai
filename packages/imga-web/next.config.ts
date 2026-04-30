import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // standalone output keeps the production Docker image small —
  // the runner stage copies only .next/standalone + .next/static
  // + public/.
  output: "standalone",
  reactStrictMode: true,
};

export default nextConfig;
