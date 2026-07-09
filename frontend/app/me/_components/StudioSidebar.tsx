"use client";

import { Upload, User as UserIcon } from "lucide-react";

import { Avatar } from "./StudioPanels";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { joinedDate } from "../_lib/studio-format";
import { STUDIO_SECTIONS } from "../_lib/studio-navigation";
import type { Section } from "../_lib/studio-state";
import type { StudioController } from "../_lib/use-studio-controller";

export function StudioSidebar({
  onCreate,
  onEditProfile,
  onSwitchSection,
  section,
  user,
}: {
  onCreate: () => void;
  onEditProfile: () => void;
  onSwitchSection: (section: Section) => void;
  section: Section;
  user: StudioController["user"];
}) {
  return (
    <aside className="flex flex-col gap-5">
      <Card className="rounded-lg border-slate-200/80 bg-white/90 text-center shadow-sm">
        <CardContent className="flex flex-col items-center gap-3 p-6">
          <Avatar user={user} size="large" />
          <div>
            <h2 className="font-display text-2xl font-semibold tracking-normal text-slate-950">{user.name}</h2>
            <span className="text-sm font-semibold text-indigo-600">Creator</span>
            <p className="mt-1 text-sm text-slate-500">Joined {joinedDate(user.created_at)}</p>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-3">
        <Button className="rounded-lg" onClick={onCreate} type="button">
          <Upload size={16} />
          Create New Game
        </Button>
        <Button className="rounded-lg" onClick={onEditProfile} type="button" variant="outline">
          <UserIcon size={16} />
          Edit Profile
        </Button>
      </div>

      <nav className="grid gap-2" aria-label="Studio sections">
        {STUDIO_SECTIONS.map((item) => {
          const Icon = item.icon;
          return (
            <button
              className={cn(
                "flex items-center gap-3 rounded-lg border px-4 py-3 text-left text-sm font-semibold transition",
                section === item.id
                  ? "border-indigo-200 bg-indigo-50 text-indigo-700"
                  : "border-slate-200 bg-white/80 text-slate-600 hover:border-indigo-200 hover:bg-indigo-50/40",
              )}
              key={item.id}
              onClick={() => onSwitchSection(item.id)}
              type="button"
            >
              <Icon size={20} />
              {item.label}
            </button>
          );
        })}
      </nav>
    </aside>
  );
}
