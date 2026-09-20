"use client";

import { useEffect } from "react";

import { Button, ErrorState } from "@/components/ui";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Logged for the developer; the user only ever sees plain language.
    console.error("RivalRadar render error:", error);
  }, [error]);

  return (
    <div className="animate-page max-w-[62ch] py-16">
      <ErrorState
        title="This page could not be displayed"
        message={
          error.message ||
          "An unexpected error occurred while rendering. If the API is not running, start it with rivalradar serve."
        }
      />
      <div className="mt-6 pl-4">
        <Button onClick={reset}>Try again</Button>
      </div>
    </div>
  );
}
