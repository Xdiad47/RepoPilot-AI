"use client";

import { RefreshCw } from "lucide-react";
import { SiteHeader } from "@/components/site-header";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

export default function GlobalError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <>
      <SiteHeader />
      <main className="mx-auto w-full max-w-xl flex-1 px-4 py-24">
        <Alert
          tone="danger"
          title="Something went wrong"
          action={
            <Button variant="outline" size="sm" onClick={reset}>
              <RefreshCw className="h-3.5 w-3.5" aria-hidden /> Try again
            </Button>
          }
        >
          An unexpected error occurred while rendering this page. Your investigation, if any, is safe on the server.
        </Alert>
      </main>
    </>
  );
}
