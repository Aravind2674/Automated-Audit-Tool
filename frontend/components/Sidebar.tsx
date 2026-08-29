"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";

import Icon from "./Icon";

/**
 * ONE nav pattern, used identically on every page.
 *
 * Reconciled from the five mockups: three used the placeholder-SVG <img> logo
 * treatment, two used a Material Symbol glyph instead (no two mockups agreed);
 * this uses the real logo file, every time. Settings/Support (present in every
 * mockup's sidebar) are omitted -- confirmed with the project owner rather than
 * assumed, since neither corresponds to anything the app has.
 */
const NAV = [
  { href: "/", label: "Overview", icon: "dashboard" },
  { href: "/findings", label: "Findings", icon: "troubleshoot" },
  { href: "/history", label: "History", icon: "history" },
  { href: "/exceptions", label: "Exceptions", icon: "warning" },
  { href: "/runs", label: "Runs", icon: "play_circle" },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <nav className="fixed left-0 top-0 z-40 hidden h-full w-64 flex-col gap-sm border-r border-outline-variant bg-surface py-lg md:flex">
      <div className="mb-md flex items-center gap-sm px-md">
        <Image src="/audittool_logo.png" alt="AuditTool" width={32} height={32} className="rounded" priority />
        <h1 className="font-headline-sm text-headline-sm font-bold text-primary">AuditTool</h1>
      </div>

      <div className="flex flex-1 flex-col gap-xs px-sm">
        {NAV.map((item) => {
          const active = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={
                active
                  ? "flex items-center gap-sm rounded bg-secondary-container px-sm py-sm font-semibold text-on-secondary-container"
                  : "flex items-center gap-sm rounded px-sm py-sm text-on-surface-variant transition-colors duration-100 hover:bg-surface-container-high"
              }
            >
              <Icon name={item.icon} filled={active} />
              <span className="font-body-md text-body-md">{item.label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
