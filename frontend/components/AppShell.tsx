"use client";

import Header from "./Header";
import Icon from "./Icon";
import Login from "./Login";
import Sidebar from "./Sidebar";
import { DashboardProvider, useDashboard } from "../lib/dashboard-context";

function Shell({ title, children }: { title: string; children: React.ReactNode }) {
  const { error, needsLogin, reload } = useDashboard();

  if (needsLogin) return <Login onSuccess={reload} />;
  if (error) {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center gap-sm bg-surface p-lg text-center">
        <Icon name="error" className="text-[32px] text-error" />
        <p className="font-headline-sm text-headline-sm text-on-surface">Couldn&apos;t reach the API</p>
        <p className="max-w-sm font-data-mono text-data-mono text-on-surface-variant">{error}</p>
        <button
          onClick={reload}
          className="mt-sm rounded bg-primary px-md py-sm font-body-sm text-body-sm font-semibold text-on-primary hover:opacity-90"
        >
          Retry
        </button>
      </main>
    );
  }

  // No `!data` gate here: the shell (sidebar/header) renders as soon as auth is
  // resolved, and each page's own content component renders its own skeleton
  // while `data` is still null -- matching its real layout instead of blocking
  // the whole app behind one generic spinner.
  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <div className="flex min-h-screen flex-1 flex-col md:ml-64">
        <Header title={title} />
        <main className="flex-1 p-margin">{children}</main>
      </div>
    </div>
  );
}

/** Wraps one route: shared auth, sidebar, header -- identical on every page. */
export default function AppShell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <DashboardProvider>
      <Shell title={title}>{children}</Shell>
    </DashboardProvider>
  );
}
