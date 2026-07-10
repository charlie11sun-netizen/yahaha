import { Brain, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { MemoryItem, MemoryProfile, MemorySettings } from "@/lib/types";
import { memoryDate, memoryScopeLabel, profileScopeLabel } from "../_lib/studio-format";
import { EmptyState, Panel } from "./StudioPrimitives";

export function MemorySection({
  deletingId,
  items,
  loading,
  newMemoryText,
  onAdd,
  onDelete,
  onEditProfile,
  onTextChange,
  onUpdateSettings,
  saving,
  savingSettings,
  settings,
  profileActionId,
  profiles,
}: {
  deletingId: string | null;
  items: MemoryItem[];
  loading: boolean;
  newMemoryText: string;
  onAdd: () => void;
  onDelete: (item: MemoryItem) => void;
  onEditProfile: (profile: MemoryProfile) => void;
  onTextChange: (value: string) => void;
  onUpdateSettings: (patch: Partial<MemorySettings>) => void;
  saving: boolean;
  savingSettings: boolean;
  settings?: MemorySettings;
  profileActionId: string | null;
  profiles: MemoryProfile[];
}) {
  const visibleProfiles = profiles.filter((profile) => profile.status === "active");
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <Panel title="Memory controls">
        <p className="text-sm leading-6 text-slate-600">
          Memory helps generation and revision preserve your preferences. Current prompts always override memory.
        </p>
        <div className="grid gap-3">
          <ToggleRow
            checked={settings?.enabled ?? true}
            disabled={savingSettings || !settings}
            label="Enable memory"
            onChange={(checked) => onUpdateSettings({ enabled: checked })}
          />
          <ToggleRow
            checked={settings?.allow_cross_game_memory ?? true}
            disabled={savingSettings || !settings || settings.enabled === false}
            label="Use long-term preferences across games"
            onChange={(checked) => onUpdateSettings({ allow_cross_game_memory: checked })}
          />
          <ToggleRow
            checked={settings?.allow_memory_extraction ?? true}
            disabled={savingSettings || !settings || settings.enabled === false}
            label="Learn from successful previews and revisions"
            onChange={(checked) => onUpdateSettings({ allow_memory_extraction: checked })}
          />
          <label className="grid gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm font-semibold text-slate-700">
            Retain stored memories
            <select
              className="rounded-md border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-indigo-300 focus:ring-4 focus:ring-indigo-100"
              disabled={savingSettings || !settings}
              onChange={(event) => onUpdateSettings({
                retention_days: event.target.value ? Number(event.target.value) : null,
              })}
              value={settings?.retention_days ?? ""}
            >
              <option value="">Until I delete them</option>
              <option value="30">30 days</option>
              <option value="90">90 days</option>
              <option value="365">1 year</option>
            </select>
            <small className="font-normal text-slate-500">Retention limits also apply to pinned memories.</small>
          </label>
        </div>
      </Panel>

      <Panel title="Add manual memory">
        <label className="grid gap-2 text-sm font-semibold text-slate-700">
          Preference or constraint
          <textarea
            className="min-h-32 resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm leading-6 outline-none focus:border-indigo-300 focus:ring-4 focus:ring-indigo-100"
            maxLength={4000}
            onChange={(event) => onTextChange(event.target.value)}
            placeholder="Example: I prefer pixel art and medium difficulty by default."
            value={newMemoryText}
          />
        </label>
        <Button className="rounded-lg" disabled={saving || !newMemoryText.trim()} onClick={onAdd} type="button">
          <Brain size={16} />
          {saving ? "Saving..." : "Save memory"}
        </Button>
      </Panel>

      <Panel title="Current memory profile">
        <p className="text-sm leading-6 text-slate-600">
          This is the current synthesized state used by generation. Candidate memories are observed silently and only become active after repeated support.
        </p>
        {loading ? (
          <EmptyState>Loading memory profile...</EmptyState>
        ) : visibleProfiles.length === 0 ? (
          <EmptyState>No active profile yet</EmptyState>
        ) : (
          <div className="grid gap-3">
            {visibleProfiles.map((profile) => (
              <article className="rounded-lg border border-slate-200 bg-slate-50 p-4" key={profile.id}>
                <div className="space-y-2">
                  <span className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
                    {profileScopeLabel(profile)} - {profile.profile_key}
                  </span>
                  <strong className="block text-sm font-semibold text-slate-950">{profile.summary_text}</strong>
                  <small className="block text-xs text-slate-500">
                    support {profile.support_count} - utility {Math.round(profile.utility_score * 100)}%
                  </small>
                  <small className="block text-xs text-slate-500">
                    {profile.status} - {profile.explicitness} - confidence {Math.round(profile.confidence * 100)}% - v{profile.version}
                  </small>
                </div>
                <Button
                  className="mt-3 rounded-lg"
                  disabled={profileActionId === profile.id}
                  onClick={() => onEditProfile(profile)}
                  type="button"
                  variant="outline"
                >
                  Correct
                </Button>
              </article>
            ))}
          </div>
        )}
      </Panel>

      <Panel title="Stored memories">
        {loading ? (
          <EmptyState>Loading memories...</EmptyState>
        ) : items.length === 0 ? (
          <EmptyState>No memories yet</EmptyState>
        ) : (
          <div className="grid gap-3">
            {items.map((item) => (
              <article className="grid grid-cols-[1fr_auto] gap-3 rounded-lg border border-slate-200 bg-slate-50 p-4" key={item.id}>
                <div className="min-w-0 space-y-2">
                  <span className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
                    {memoryScopeLabel(item)} - {item.category}
                  </span>
                  <strong className="block text-sm font-semibold text-slate-950">{item.raw_text}</strong>
                  {item.extracted_text ? <p className="text-sm leading-6 text-slate-600">{item.extracted_text}</p> : null}
                  <small className="block text-xs text-slate-500">
                    {item.source_type} - importance {item.importance} - {memoryDate(item.created_at)}
                  </small>
                </div>
                <Button
                  aria-label="Delete memory"
                  className="rounded-lg text-rose-700 hover:text-rose-700"
                  disabled={deletingId === item.id}
                  onClick={() => onDelete(item)}
                  size="icon"
                  type="button"
                  variant="outline"
                >
                  <Trash2 size={15} />
                </Button>
              </article>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}
function ToggleRow({
  checked,
  disabled,
  label,
  onChange,
}: {
  checked: boolean;
  disabled: boolean;
  label: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm font-semibold text-slate-700">
      <span>{label}</span>
      <input
        checked={checked}
        className="size-4 accent-indigo-600"
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        type="checkbox"
      />
    </label>
  );
}
