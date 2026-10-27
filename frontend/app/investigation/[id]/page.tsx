import type { Metadata } from "next";
import { Suspense } from "react";
import { InvestigationView } from "@/components/investigation/investigation-view";
import { WorkspaceSkeleton } from "@/components/investigation/states";
import { SiteHeader } from "@/components/site-header";

export const metadata: Metadata = { title: "Investigation", robots: { index: false } };

export default function InvestigationPage(props: PageProps<"/investigation/[id]">) {
  return (
    <>
      <SiteHeader />
      <main className="flex-1">
        {/* `params` is runtime data, so it is read inside a Suspense boundary (Cache Components). */}
        <Suspense fallback={<WorkspaceSkeleton />}>
          <Resolved params={props.params} />
        </Suspense>
      </main>
    </>
  );
}

async function Resolved({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <InvestigationView id={id} />;
}
