import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  // Lint runs as its own step (`npm run lint`, CI); keep `next build` (and the Docker image) lint-free.
  eslint: { ignoreDuringBuilds: true },
};

export default nextConfig;
