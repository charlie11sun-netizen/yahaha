"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Brain,
  ChevronRight,
  ExternalLink,
  Eye,
  EyeOff,
  Play,
  Sparkles,
  Trash2,
  Upload,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import type { ElementType, ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import {
  formatBytes,
  memoryDate,
  memoryScopeLabel,
  profileScopeLabel,
  shortId,
  taskActionLabel,
  taskStatusLabel,
  taskStep,
} from "../_lib/studio-format";
import { api } from "@/lib/api";
import { coverBackgroundStyle, STUDIO_COVER_BACKGROUND } from "@/lib/cover";
import { useToast } from "@/lib/toast";
import type { Game, GameVersion, MemoryItem, MemoryProfile, MemorySettings, Task } from "@/lib/types";

export function StatCard({ icon: Icon, label, value }: { icon: ElementType; label: string; value: string }) {
  return (
    <Card className="rounded-lg border-slate-200/80 bg-white/90 shadow-sm">
      <CardContent className="flex items-center gap-4 p-5">
        <span className="flex size-11 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600">
          <Icon size={24} />
        </span>
        <div>
          <p className="text-sm font-medium text-slate-500">{label}</p>
          <strong className="font-display text-2xl font-semibold tracking-normal text-slate-950">{value}</strong>
        </div>
      </CardContent>
    </Card>
  );
}

export function Avatar({ size, user }: { size: "large" | "medium"; user: { init: string; name: string } }) {
  return (
    <div
      aria-label={user.name}
      className={cn(
        "flex items-center justify-center rounded-lg bg-indigo-600 font-display font-semibold text-white shadow-lg shadow-indigo-500/25",
        size === "large" ? "size-24 text-3xl" : "size-14 text-xl",
      )}
    >
      {user.init}
    </div>
  );
}

export function Panel({
  actionLabel,
  children,
  onAction,
  title,
}: {
  actionLabel?: string;
  children: ReactNode;
  onAction?: () => void;
  title: string;
}) {
  return (
    <Card className="rounded-lg border-slate-200/80 bg-white/90 shadow-sm">
      <CardHeader className="flex-row items-center justify-between gap-4">
        <CardTitle className="font-display text-xl font-semibold tracking-normal text-slate-950">{title}</CardTitle>
        {actionLabel && onAction ? (
          <Button className="rounded-lg" onClick={onAction} type="button" variant="outline">
            {actionLabel}
            <ChevronRight size={18} />
          </Button>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-5">{children}</CardContent>
    </Card>
  );
}

export function GameGrid({
  emptyLabel,
  games,
  onPublish,
  onUnpublish,
  onDelete,
  publishingId,
  busyId,
  readonly = false,
}: {
  emptyLabel: string;
  games: Game[];
  onPublish: (game: Game) => void;
  onUnpublish?: (game: Game) => void;
  onDelete?: (game: Game) => void;
  publishingId: string | null;
  busyId?: string | null;
  readonly?: boolean;
}) {
  if (games.length === 0) return <EmptyState>{emptyLabel}</EmptyState>;

  return (
    <div className="grid gap-5 xl:grid-cols-2">
      {games.map((game) => (
        <StudioGameCard
          busy={publishingId === game.id || busyId === game.id}
          game={game}
          key={game.id}
          onDelete={onDelete}
          onPublish={onPublish}
          onUnpublish={onUnpublish}
          readonly={readonly}
        />
      ))}
    </div>
  );
}

function StudioGameCard({
  busy,
  game,
  onDelete,
  onPublish,
  onUnpublish,
  readonly,
}: {
  busy: boolean;
  game: Game;
  onDelete?: (game: Game) => void;
  onPublish: (game: Game) => void;
  onUnpublish?: (game: Game) => void;
  readonly: boolean;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const flash = useToast();
  const [versionsOpen, setVersionsOpen] = useState(false);
  const [activatingVersion, setActivatingVersion] = useState<string | null>(null);
  const isPublished = game.status === "published";
  const versionsQ = useQuery({
    queryKey: ["game-versions", game.id],
    queryFn: () => api.gameVersions(game.id),
    enabled: versionsOpen && !readonly,
  });

  const activateVersion = async (version: string) => {
    try {
      setActivatingVersion(version);
      await api.activateVersion(game.id, version);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["me-games"] }),
        queryClient.invalidateQueries({ queryKey: ["games"] }),
        queryClient.invalidateQueries({ queryKey: ["game", game.id] }),
        queryClient.invalidateQueries({ queryKey: ["game-versions", game.id] }),
      ]);
      flash(`${game.title} is now on ${version}`);
    } catch (err) {
      flash(err instanceof Error ? err.message : "Could not switch version");
    } finally {
      setActivatingVersion(null);
    }
  };

  return (
    <Card className="overflow-hidden rounded-lg border-slate-200/80 bg-white py-0 shadow-sm">
      <button
        className="relative aspect-[16/9] w-full bg-slate-900 bg-cover bg-center text-left"
        onClick={() => router.push(isPublished ? `/games/${game.id}` : `/play/${game.id}`)}
        style={coverBackgroundStyle(game.cover, STUDIO_COVER_BACKGROUND)}
        type="button"
      >
        <span className="absolute inset-0 bg-gradient-to-t from-slate-950/70 via-transparent to-transparent" />
        <Badge
          className={cn(
            "absolute left-3 top-3 border-white/20",
            isPublished ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700",
          )}
          variant="outline"
        >
          {isPublished ? "Published" : "Draft"}
        </Badge>
      </button>
      <CardContent className="space-y-4 p-5">
        <div>
          <h3 className="font-display text-xl font-semibold tracking-normal text-slate-950">{game.title}</h3>
          <div className="mt-3 flex flex-wrap gap-2">
            {(game.tags.length ? game.tags : [game.genre]).slice(0, 3).map((tag) => (
              <Badge className="border-slate-200 bg-slate-50 text-slate-600" key={tag} variant="outline">
                {tag}
              </Badge>
            ))}
          </div>
        </div>
        <p className="line-clamp-2 text-sm leading-6 text-slate-600">{game.summary}</p>
        <div className="flex flex-wrap items-center gap-2">
          <Button className="rounded-lg" onClick={() => router.push(`/play/${game.id}`)} type="button" variant="outline">
            {isPublished ? <Play size={15} /> : <Eye size={15} />}
            {isPublished ? "Play" : "Preview"}
          </Button>
          {isPublished ? (
            <Button className="rounded-lg" onClick={() => router.push(`/games/${game.id}`)} type="button" variant="outline">
              View
              <ExternalLink size={14} />
            </Button>
          ) : null}
          {!readonly && !isPublished ? (
            <Button className="rounded-lg" disabled={busy} onClick={() => onPublish(game)} type="button">
              <Upload size={15} />
              {busy ? "Working..." : "Publish"}
            </Button>
          ) : null}
          {!readonly && isPublished && onUnpublish ? (
            <Button className="rounded-lg" disabled={busy} onClick={() => onUnpublish(game)} type="button" variant="outline">
              <EyeOff size={14} />
              Unpublish
            </Button>
          ) : null}
          {!readonly ? (
            <Button className="rounded-lg" onClick={() => setVersionsOpen((current) => !current)} type="button" variant="outline">
              Versions
              <ChevronRight size={14} />
            </Button>
          ) : null}
          {!readonly && onDelete ? (
            <Button
              aria-label="Delete game"
              className="ml-auto rounded-lg text-rose-700 hover:text-rose-700"
              disabled={busy}
              onClick={() => onDelete(game)}
              size="icon"
              type="button"
              variant="outline"
            >
              <Trash2 size={14} />
            </Button>
          ) : null}
        </div>
        {versionsOpen && !readonly ? (
          <VersionPanel
            activatingVersion={activatingVersion}
            currentVersion={game.version}
            loading={versionsQ.isLoading}
            onActivate={activateVersion}
            onPreview={(version) => router.push(`/play/${game.id}?version=${encodeURIComponent(version)}`)}
            versions={versionsQ.data?.items ?? []}
          />
        ) : null}
      </CardContent>
    </Card>
  );
}

function VersionPanel({
  activatingVersion,
  currentVersion,
  loading,
  onActivate,
  onPreview,
  versions,
}: {
  activatingVersion: string | null;
  currentVersion: string;
  loading: boolean;
  onActivate: (version: string) => void;
  onPreview: (version: string) => void;
  versions: GameVersion[];
}) {
  if (loading) return <EmptyState>Loading versions...</EmptyState>;
  if (versions.length === 0) return <EmptyState>No versions saved yet.</EmptyState>;
  return (
    <div className="grid gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
      {versions.map((version) => (
        <div className="grid gap-3 rounded-lg border border-slate-200 bg-white p-3 md:grid-cols-[1fr_auto_auto] md:items-center" key={version.version}>
          <div className="min-w-0">
            <strong className="text-sm font-semibold text-slate-950">{version.version}</strong>
            <span className="mt-1 block break-all font-mono text-xs text-slate-500">
              {formatBytes(version.size_bytes)} - {version.sha256 ? version.sha256.slice(0, 10) : "no hash"}
            </span>
          </div>
          <Button className="rounded-lg" onClick={() => onPreview(version.version)} type="button" variant="outline">
            Preview
          </Button>
          <Button
            className="rounded-lg"
            disabled={version.version === currentVersion || activatingVersion === version.version}
            onClick={() => onActivate(version.version)}
            type="button"
          >
            {version.version === currentVersion ? "Current" : activatingVersion === version.version ? "Switching" : "Activate"}
          </Button>
        </div>
      ))}
    </div>
  );
}

export function TaskTable({
  deletingId,
  emptyLabel,
  onDelete,
  onOpen,
  tasks,
}: {
  deletingId: string | null;
  emptyLabel: string;
  onDelete: (task: Task) => void;
  onOpen: (task: Task) => void;
  tasks: Task[];
}) {
  if (tasks.length === 0) return <EmptyState>{emptyLabel}</EmptyState>;

  return (
    <div className="overflow-hidden rounded-lg border border-slate-200">
      <div className="hidden grid-cols-[minmax(0,1.4fr)_120px_120px_120px_160px] gap-3 bg-slate-50 px-4 py-3 text-xs font-bold uppercase tracking-[0.14em] text-slate-500 lg:grid">
        <span>Task / Prompt</span>
        <span>Task ID</span>
        <span>Status</span>
        <span>Step</span>
        <span>Action</span>
      </div>
      {tasks.map((task) => (
        <div className="grid gap-3 border-t border-slate-200 bg-white px-4 py-4 lg:grid-cols-[minmax(0,1.4fr)_120px_120px_120px_160px] lg:items-center" key={task.id}>
          <div className="flex min-w-0 gap-3">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600">
              <Sparkles size={16} />
            </span>
            <div className="min-w-0">
              <strong className="line-clamp-1 text-sm font-semibold text-slate-950">{task.game_title || task.idea || "Untitled game"}</strong>
              <p className="line-clamp-2 text-sm leading-6 text-slate-500">{task.idea}</p>
            </div>
          </div>
          <span className="font-mono text-xs text-slate-500">{shortId(task.id)}</span>
          <Badge className={taskBadgeClass(task.status)} variant="outline">
            {taskStatusLabel(task.status)}
          </Badge>
          <span className="text-sm text-slate-600">{taskStep(task)}</span>
          <div className="flex items-center gap-2">
            <Button className="rounded-lg" onClick={() => onOpen(task)} type="button" variant="outline">
              {taskActionLabel(task)}
              <ChevronRight size={17} />
            </Button>
            <Button
              aria-label="Delete task"
              className="rounded-lg text-rose-700 hover:text-rose-700"
              disabled={deletingId === task.id}
              onClick={() => onDelete(task)}
              size="icon"
              type="button"
              variant="outline"
            >
              <Trash2 size={15} />
            </Button>
          </div>
        </div>
      ))}
    </div>
  );
}

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

function EmptyState({ children }: { children: ReactNode }) {
  return <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 p-8 text-center text-sm text-slate-500">{children}</div>;
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

function taskBadgeClass(status: Task["status"]) {
  if (status === "succeeded") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (status === "failed") return "border-rose-200 bg-rose-50 text-rose-700";
  if (status === "cancelled") return "border-amber-200 bg-amber-50 text-amber-700";
  return "border-indigo-200 bg-indigo-50 text-indigo-700";
}
