import Link from "next/link";

import { Button } from "@/components/ui";

export default function NotFound() {
  return (
    <div className="animate-page flex flex-col items-center justify-center py-24 text-center">
      <p className="eyebrow">404</p>
      <h1 className="mt-2 text-[18px] font-semibold tracking-[-0.02em]">Page not found</h1>
      <p className="mt-1.5 max-w-sm text-[13px] text-[var(--ink-soft)]">
        That page does not exist in RivalRadar.
      </p>
      <div className="mt-5">
        <Link href="/">
          <Button>Back to dashboard</Button>
        </Link>
      </div>
    </div>
  );
}
