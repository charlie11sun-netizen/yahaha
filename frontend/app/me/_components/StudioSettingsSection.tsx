"use client";

import type { ReactNode } from "react";
import { BadgeCheck, KeyRound, Trash2 } from "lucide-react";

import { Avatar, Panel } from "./StudioPanels";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { avatarChoices } from "../_lib/studio-format";
import type { StudioController } from "../_lib/use-studio-controller";

export function StudioSettingsSection({ studio }: { studio: StudioController }) {
  const {
    changePassword,
    changingPassword,
    currentPassword,
    deleteAccount,
    deleting,
    displayName,
    email,
    newPassword,
    saveProfile,
    savingProfile,
    setAvatar,
    setCurrentPassword,
    setDisplayName,
    setEmail,
    setNewPassword,
    user,
  } = studio;

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
      <Panel title="Public profile">
        <div className="grid gap-4 rounded-lg border border-slate-200 bg-slate-50 p-4 sm:grid-cols-[auto_1fr] sm:items-center">
          <Avatar user={user} size="medium" />
          <div>
            <h3 className="font-display text-xl font-semibold tracking-normal text-slate-950">{user.name}</h3>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              Your public creator identity is used across published games, comments, and playable results.
            </p>
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Display name">
            <Input maxLength={120} onChange={(event) => setDisplayName(event.target.value)} value={displayName} />
          </Field>
          <Field label="Email">
            <Input onChange={(event) => setEmail(event.target.value)} type="email" value={email} />
          </Field>
        </div>

        <div className="grid gap-3">
          <span className="text-sm font-semibold text-slate-700">Avatar mark</span>
          <div className="flex flex-wrap gap-2">
            {avatarChoices(user.name).map((mark) => (
              <button
                className={cn(
                  "flex size-10 items-center justify-center rounded-lg border text-sm font-semibold transition",
                  user.init === mark
                    ? "border-indigo-300 bg-indigo-600 text-white"
                    : "border-slate-200 bg-white text-slate-700 hover:border-indigo-200 hover:bg-indigo-50",
                )}
                key={mark}
                onClick={() => setAvatar(mark)}
                type="button"
              >
                {mark}
              </button>
            ))}
          </div>
        </div>

        <Button className="w-fit rounded-lg" disabled={savingProfile} onClick={saveProfile} type="button">
          <BadgeCheck size={16} />
          {savingProfile ? "Saving..." : "Save Profile"}
        </Button>
      </Panel>

      <div className="flex flex-col gap-6">
        <Panel title="Change password">
          <Field label="Current password">
            <Input
              onChange={(event) => setCurrentPassword(event.target.value)}
              placeholder="Required for password accounts"
              type="password"
              value={currentPassword}
            />
          </Field>
          <Field label="New password">
            <Input onChange={(event) => setNewPassword(event.target.value)} type="password" value={newPassword} />
          </Field>
          <Button className="w-fit rounded-lg" disabled={changingPassword} onClick={changePassword} type="button" variant="outline">
            <KeyRound size={16} />
            {changingPassword ? "Updating..." : "Update password"}
          </Button>
        </Panel>

        <Panel title="Danger zone">
          <p className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm leading-6 text-rose-700">
            Deleting your account permanently removes your games, generation tasks, and data. This cannot be undone.
          </p>
          <Button className="w-fit rounded-lg" disabled={deleting} onClick={deleteAccount} type="button" variant="destructive">
            <Trash2 size={16} />
            {deleting ? "Deleting..." : "Delete account"}
          </Button>
        </Panel>
      </div>
    </div>
  );
}

function Field({ children, label }: { children: ReactNode; label: string }) {
  return (
    <label className="grid gap-2 text-sm font-semibold text-slate-700">
      <span>{label}</span>
      {children}
    </label>
  );
}
