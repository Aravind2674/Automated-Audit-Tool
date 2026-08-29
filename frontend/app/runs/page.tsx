import AppShell from "@/components/AppShell";
import RunsContent from "@/components/RunsContent";

export const dynamic = "force-dynamic";

export default function Page() {
  return (
    <AppShell title="Runs">
      <RunsContent />
    </AppShell>
  );
}
