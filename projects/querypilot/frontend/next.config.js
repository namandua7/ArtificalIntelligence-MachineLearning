/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // NEXT_DIST_DIR lets a production build run next to a live `next dev` without clobbering its .next cache.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  experimental: {
    // Import only the icons/components actually used instead of whole barrel files.
    optimizePackageImports: ["lucide-react", "framer-motion", "recharts", "@radix-ui/react-dialog", "@radix-ui/react-tooltip"],
  },
};

module.exports = nextConfig;
