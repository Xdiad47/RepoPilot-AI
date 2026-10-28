import { NotFoundState } from "@/components/investigation/states";
import { SiteHeader } from "@/components/site-header";

export default function NotFound() {
  return (
    <>
      <SiteHeader />
      <main id="main" className="flex-1">
        <NotFoundState invalid />
      </main>
    </>
  );
}
