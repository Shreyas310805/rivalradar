import type { Metadata } from "next";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";

import { Shell } from "@/components/Shell";

import "./globals.css";

export const metadata: Metadata = {
  title: "RivalRadar — Competitive Intelligence",
  description:
    "Track competitor websites, filter the noise, and see only the changes that matter.",
};

/**
 * Runs blocking in <head>, before first paint. Two jobs, both tiny:
 *
 *  - apply the stored theme, so the page never flashes light before dark;
 *  - mark the document as scripted.
 *
 * The second one matters more than it looks. Everything that animates in on
 * scroll starts at `opacity: 0` and is revealed by JavaScript, so those rules
 * are scoped to `.js`. If this script does not run — or hydration fails — the
 * server-rendered content is simply visible rather than invisible forever.
 */
const BOOT_SCRIPT = `
(function () {
  var root = document.documentElement;
  root.classList.add('js');
  try {
    // Light is the primary experience, so it is the default. Dark is opt-in
    // via the toggle and remembered from then on — we deliberately do not
    // follow prefers-color-scheme on a first visit.
    var stored = localStorage.getItem('rivalradar-theme');
    root.setAttribute('data-theme', stored === 'dark' ? 'dark' : 'light');
  } catch (e) {
    root.setAttribute('data-theme', 'light');
  }
})();
`;

/**
 * Geist is self-hosted through next/font — the files ship with the bundle, so
 * there is no render-blocking request to a font CDN and no layout shift, and
 * the app keeps working with no network access to third parties.
 */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${GeistSans.variable} ${GeistMono.variable}`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: BOOT_SCRIPT }} />
      </head>
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
