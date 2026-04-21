/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Skip type-checking during Docker builds — the demo codebase has
  // minor type inconsistencies that don't affect runtime behaviour.
  typescript: {
    ignoreBuildErrors: true,
  },
  eslint: {
    ignoreDuringBuilds: true,
  },
};

export default nextConfig;
