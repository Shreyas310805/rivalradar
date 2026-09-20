import type { NextConfig } from "next";

/**
 * Two build modes.
 *
 *   dev / `npm run build`  – a normal Next server. `/api/*` is proxied to the
 *                            backend, so the browser makes same-origin calls
 *                            and there is no CORS to configure locally.
 *
 *   `npm run build:static` – a static export for GitHub Pages. Pages serves
 *                            files, not a Node server, so there is no proxy:
 *                            the browser calls the Render backend directly
 *                            and the backend's CORS_ORIGINS must name the
 *                            Pages origin.
 *
 * Static export is opt-in rather than the default so local development and
 * the Docker image keep working exactly as before.
 */
const isStaticExport = process.env.BUILD_TARGET === "static";

/**
 * Base path for a GitHub **project** site.
 *
 * A repository site lives at https://<user>.github.io/<repo>/, so every asset
 * and link needs the /<repo> prefix. A user site (<user>.github.io) is served
 * from the root and needs none — leave NEXT_PUBLIC_BASE_PATH empty there.
 * The deploy workflow sets it automatically from the repository name.
 */
const basePath = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/$/, "");

if (isStaticExport && !process.env.NEXT_PUBLIC_API_URL) {
  // Failing the build is the kind thing to do. A static export with no API
  // URL falls back to same-origin /api/..., which on GitHub Pages is a 404 —
  // producing a site that looks fine and shows an error on every panel.
  throw new Error(
    "NEXT_PUBLIC_API_URL must be set for a static export. Point it at your " +
      "Render backend, e.g. https://rivalradar-api.onrender.com",
  );
}

const nextConfig: NextConfig = {
  reactStrictMode: true,

  // The floating dev badge sits on top of the sidebar footer, hiding the
  // Settings link and the theme control. Build output is unaffected.
  devIndicators: false,

  ...(isStaticExport
    ? {
        output: "export" as const,
        // GitHub Pages resolves /changes/ to /changes/index.html. Without the
        // trailing slash the export emits changes.html, which Pages serves
        // inconsistently across user and project sites.
        trailingSlash: true,
        // No Next image server exists in a static export.
        images: { unoptimized: true },
        ...(basePath ? { basePath, assetPrefix: basePath } : {}),
      }
    : {}),

  // Standalone output is only needed for the optional Docker image.
  ...(process.env.DOCKER_BUILD === "1" ? { output: "standalone" as const } : {}),

  // Rewrites need a server, so they exist only in the non-export builds.
  // Next warns and ignores them under `output: "export"`; omitting them keeps
  // the build output clean and the intent obvious.
  ...(isStaticExport
    ? {}
    : {
        async rewrites() {
          const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
          return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
        },
      }),
};

export default nextConfig;
