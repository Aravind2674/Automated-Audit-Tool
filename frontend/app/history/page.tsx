import AppShell from "@/components/AppShell";
import HistoryContent from "@/components/HistoryContent";

export const dynamic = "force-dynamic";

export default function Page() {
  return (
    <AppShell title="History">
      <HistoryContent />
    </AppShell>
  );
}
