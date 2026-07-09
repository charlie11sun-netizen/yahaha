"use client";

import { Database, Gamepad2, Globe2, MessageCircle, PlaySquare } from "lucide-react";

import { cn } from "@/lib/utils";
import { SHELL, footerColumns } from "../_lib/explore-data";

const socialLinks = [
  { label: "Community", icon: MessageCircle },
  { label: "Games", icon: Gamepad2 },
  { label: "Play", icon: PlaySquare },
  { label: "Data", icon: Database },
];

export function ExploreFooter({
  onFooterLink,
  onRoute,
}: {
  onFooterLink: (label: string) => void;
  onRoute: (path: string) => void;
}) {
  return (
    <footer className="border-t border-slate-200/80 bg-white/70 backdrop-blur">
      <div className={cn(SHELL, "grid grid-cols-2 gap-8 py-12 md:grid-cols-[1.8fr_repeat(3,0.8fr)]")}>
        <div className="col-span-2 md:col-span-1">
          <div className="flex items-center gap-2.5">
            <span className="flex size-8 items-center justify-center rounded-lg bg-gradient-to-br from-violet-600 to-blue-500 text-white shadow-md shadow-violet-500/30">
              <Globe2 className="size-4.5" />
            </span>
            <strong className="font-display text-base font-bold text-slate-900">GameWeave AI</strong>
          </div>
          <p className="mt-3 max-w-56 text-xs leading-relaxed text-slate-500">
            The AI-native platform for creating, sharing, and playing web games.
          </p>
          <div className="mt-4 flex gap-2">
            {socialLinks.map(({ icon: Icon, label }) => (
              <button
                key={label}
                type="button"
                aria-label={label}
                className="flex size-8 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 transition-colors hover:border-violet-300 hover:text-violet-600"
              >
                <Icon className="size-4" />
              </button>
            ))}
          </div>
        </div>
        {footerColumns.map((column) => (
          <div key={column.title} className="flex flex-col gap-2.5">
            <strong className="text-xs font-bold tracking-wide text-slate-900 uppercase">{column.title}</strong>
            {column.links.map((link) => (
              <button key={link} onClick={() => onFooterLink(link)} type="button" className="text-left text-xs text-slate-500 transition-colors hover:text-violet-600">
                {link}
              </button>
            ))}
          </div>
        ))}
      </div>
      <div className={cn(SHELL, "flex flex-col items-center justify-between gap-3 border-t border-slate-200/70 py-5 sm:flex-row")}>
        <p className="text-xs text-slate-400">(c) 2024 GameWeave AI. All rights reserved.</p>
        <div className="flex gap-5">
          <button onClick={() => onRoute("/privacy")} type="button" className="text-xs text-slate-400 transition-colors hover:text-violet-600">Privacy Policy</button>
          <button onClick={() => onRoute("/terms")} type="button" className="text-xs text-slate-400 transition-colors hover:text-violet-600">Terms of Service</button>
          <button onClick={() => onRoute("/about")} type="button" className="text-xs text-slate-400 transition-colors hover:text-violet-600">Docs</button>
        </div>
      </div>
    </footer>
  );
}
