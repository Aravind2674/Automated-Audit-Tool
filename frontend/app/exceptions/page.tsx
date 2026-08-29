import AppShell from "@/components/AppShell";
import ExceptionsContent from "@/components/ExceptionsContent";

export const dynamic = "force-dynamic";

export default function Page() {
  return (
    <AppShell title="Exceptions">
      <ExceptionsContent />
    </AppShell>
  );
}
