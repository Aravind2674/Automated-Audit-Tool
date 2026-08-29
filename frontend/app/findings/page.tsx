import AppShell from "@/components/AppShell";
import FindingsContent from "@/components/FindingsContent";

export const dynamic = "force-dynamic";

export default function Page() {
  return (
    <AppShell title="Findings">
      <FindingsContent />
    </AppShell>
  );
}
