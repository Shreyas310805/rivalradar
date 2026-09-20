"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

/**
 * Renders children into document.body.
 *
 * Overlays must escape their ancestors. An ancestor with a transform — which
 * includes any element running a transform-based CSS animation, such as the
 * page-entrance effect — becomes the containing block for `position: fixed`
 * descendants. A drawer nested inside one stops pinning to the viewport and
 * stretches to its own content height instead.
 *
 * Portalling to body sidesteps that entirely, and is the standard answer for
 * modals and drawers.
 */
export function Portal({ children }: { children: React.ReactNode }) {
  const [mounted, setMounted] = useState(false);

  // Portals cannot run during SSR: document does not exist there.
  useEffect(() => {
    setMounted(true);
    return () => setMounted(false);
  }, []);

  if (!mounted) return null;
  return createPortal(children, document.body);
}
