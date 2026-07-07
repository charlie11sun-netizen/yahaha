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

import {
  coverStyle,
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
import { useToast } from "@/lib/toast";
import type { Game, GameVersion, MemoryItem, MemoryProfile, MemorySettings, Task } from "@/lib/types";


export function StatCard({ icon: Icon, label, value }: { icon: ElementType; label: string; value: string }) {
  return (
    <article className="pf-studio-stat">
      <span>
        <Icon size={25} />
      </span>
      <div>
        <p>{label}</p>
        <strong>{value}</strong>
      </div>
    </article>
  );
}

export function Avatar({ size, user }: { size: "large" | "medium"; user: { init: string; name: string } }) {
  return (
    <div aria-label={user.name} className={`pf-studio-avatar is-${size}`}>
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
    <section className="pf-studio-panel">
      <header>
        <h2>{title}</h2>
        {actionLabel && onAction && (
          <button onClick={onAction} type="button">
            {actionLabel}
            <ChevronRight size={18} />
          </button>
        )}
      </header>
      {children}
    </section>
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
  if (games.length === 0) return <div className="pf-studio-empty">{emptyLabel}</div>;

  return (
    <div className="pf-studio-game-grid">
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
    <article className="pf-studio-game-card">
      <button
        className="pf-studio-game-cover"
        onClick={() => router.push(isPublished ? `/games/${game.id}` : `/play/${game.id}`)}
        style={coverStyle(game.cover)}
        type="button"
      >
        <span className={`pf-studio-status is-${isPublished ? "published" : "draft"}`}>
          {isPublished ? "Published" : "Draft"}
        </span>
      </button>
      <div className="pf-studio-game-body">
        <h3>{game.title}</h3>
        <div className="pf-studio-chip-row">
          {(game.tags.length ? game.tags : [game.genre]).slice(0, 3).map((tag) => (
            <span key={tag}>{tag}</span>
          ))}
        </div>
        <p>{game.summary}</p>
        <div className="pf-studio-card-actions">
          <div className="pf-studio-action-group">
            <button onClick={() => router.push(`/play/${game.id}`)} type="button">
              {isPublished ? <Play size={15} /> : <Eye size={15} />}
              {isPublished ? "Play" : "Preview"}
            </button>
            {isPublished ? (
              <button className="is-muted" onClick={() => router.push(`/games/${game.id}`)} type="button">
                View
                <ExternalLink size={14} />
              </button>
            ) : null}
            {!readonly && !isPublished ? (
              <button className="is-primary" disabled={busy} onClick={() => onPublish(game)} type="button">
                <Upload size={15} />
                {busy ? "Working..." : "Publish"}
              </button>
            ) : null}
            {!readonly && isPublished && onUnpublish ? (
              <button className="is-muted" disabled={busy} onClick={() => onUnpublish(game)} type="button">
                <EyeOff size={14} />
                Unpublish
              </button>
            ) : null}
            {!readonly ? (
              <button className="is-muted" onClick={() => setVersionsOpen((current) => !current)} type="button">
                Versions
                <ChevronRight size={14} />
              </button>
            ) : null}
          </div>
          {!readonly && onDelete ? (
            <button
              aria-label="Delete game"
              className="pf-studio-delete-btn"
              disabled={busy}
              onClick={() => onDelete(game)}
              type="button"
            >
              <Trash2 size={14} />
            </button>
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
      </div>
    </article>
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
  if (loading) return <div className="pf-version-panel">Loading versions...</div>;
  if (versions.length === 0) return <div className="pf-version-panel">No versions saved yet.</div>;
  return (
    <div className="pf-version-panel">
      {versions.map((version) => (
        <div className="pf-version-row" key={version.version}>
          <div>
            <strong>{version.version}</strong>
            <span>{formatBytes(version.size_bytes)} · {version.sha256 ? version.sha256.slice(0, 10) : "no hash"}</span>
          </div>
          <button onClick={() => onPreview(version.version)} type="button">
            Preview
          </button>
          <button
            disabled={version.version === currentVersion || activatingVersion === version.version}
            onClick={() => onActivate(version.version)}
            type="button"
          >
            {version.version === currentVersion ? "Current" : activatingVersion === version.version ? "Switching" : "Activate"}
          </button>
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
  if (tasks.length === 0) return <div className="pf-studio-empty">{emptyLabel}</div>;

  return (
    <div className="pf-studio-task-table">
      <div className="pf-studio-task-head">
        <span>Task / Prompt</span>
        <span>Task ID</span>
        <span>Status</span>
        <span>Step</span>
        <span>Action</span>
      </div>
      {tasks.map((task) => (
        <div className="pf-studio-task-row" key={task.id}>
          <div className="pf-studio-task-title">
            <span>
              <Sparkles size={16} />
            </span>
            <div>
              <strong>{task.game_title || task.idea || "Untitled game"}</strong>
              <p>{task.idea}</p>
            </div>
          </div>
          <span>{shortId(task.id)}</span>
          <span className={`pf-studio-task-status is-${task.status}`}>{taskStatusLabel(task.status)}</span>
          <span>{taskStep(task)}</span>
          <div className="pf-studio-task-actions">
            <button onClick={() => onOpen(task)} type="button">
              {taskActionLabel(task)}
              <ChevronRight size={17} />
            </button>
            <button
              aria-label="Delete task"
              className="pf-studio-task-delete"
              disabled={deletingId === task.id}
              onClick={() => onDelete(task)}
              type="button"
            >
              <Trash2 size={15} />
            </button>
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
    <div className="pf-memory-layout">
      <Panel title="Memory controls">
        <div className="pf-memory-copy">
          Memory helps generation and revision preserve your preferences. Current prompts always override memory.
        </div>
        <div className="pf-memory-toggles">
          <label>
            <input
              checked={settings?.enabled ?? true}
              disabled={savingSettings || !settings}
              onChange={(event) => onUpdateSettings({ enabled: event.target.checked })}
              type="checkbox"
            />
            Enable memory
          </label>
          <label>
            <input
              checked={settings?.allow_cross_game_memory ?? true}
              disabled={savingSettings || !settings || settings.enabled === false}
              onChange={(event) => onUpdateSettings({ allow_cross_game_memory: event.target.checked })}
              type="checkbox"
            />
            Use long-term preferences across games
          </label>
          <label>
            <input
              checked={settings?.allow_memory_extraction ?? true}
              disabled={savingSettings || !settings || settings.enabled === false}
              onChange={(event) => onUpdateSettings({ allow_memory_extraction: event.target.checked })}
              type="checkbox"
            />
            Learn from successful previews and revisions
          </label>
          <label>
            Retain stored memories
            <select
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
            <small>Retention limits also apply to pinned memories.</small>
          </label>
        </div>
      </Panel>

      <Panel title="Add manual memory">
        <label className="pf-studio-field pf-memory-field">
          <span>Preference or constraint</span>
          <textarea
            maxLength={4000}
            onChange={(event) => onTextChange(event.target.value)}
            placeholder="Example: I prefer pixel art and medium difficulty by default."
            value={newMemoryText}
          />
        </label>
        <div className="pf-studio-settings-actions">
          <button className="pf-studio-primary" disabled={saving || !newMemoryText.trim()} onClick={onAdd} type="button">
            <Brain size={16} />
            {saving ? "Saving..." : "Save memory"}
          </button>
        </div>
      </Panel>

      <Panel title="Current memory profile">
        <div className="pf-memory-copy">
          This is the current synthesized state used by generation. Candidate memories are observed silently and only become active after repeated support.
        </div>
        {loading ? (
          <div className="pf-studio-empty">Loading memory profile...</div>
        ) : visibleProfiles.length === 0 ? (
          <div className="pf-studio-empty">No active profile yet</div>
        ) : (
          <div className="pf-memory-profile-list">
            {visibleProfiles.map((profile) => (
              <article className={`pf-memory-profile is-${profile.status}`} key={profile.id}>
                <div className="pf-memory-profile-copy">
                  <span>{profileScopeLabel(profile)} · {profile.profile_key}</span>
                  <strong>{profile.summary_text}</strong>
                  <small>
                    support {profile.support_count} · utility {Math.round(profile.utility_score * 100)}%
                  </small>
                  <small>
                    {profile.status} · {profile.explicitness} · confidence {Math.round(profile.confidence * 100)}% · v{profile.version}
                  </small>
                </div>
                <div className="pf-memory-profile-actions">
                  <button
                    disabled={profileActionId === profile.id}
                    onClick={() => onEditProfile(profile)}
                    type="button"
                  >
                    Correct
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </Panel>

      <Panel title="Stored memories">
        {loading ? (
          <div className="pf-studio-empty">Loading memories...</div>
        ) : items.length === 0 ? (
          <div className="pf-studio-empty">No memories yet</div>
        ) : (
          <div className="pf-memory-list">
            {items.map((item) => (
              <article className="pf-memory-item" key={item.id}>
                <div>
                  <span>{memoryScopeLabel(item)} · {item.category}</span>
                  <strong>{item.raw_text}</strong>
                  {item.extracted_text ? <p>{item.extracted_text}</p> : null}
                  <small>{item.source_type} · importance {item.importance} · {memoryDate(item.created_at)}</small>
                </div>
                <button
                  aria-label="Delete memory"
                  disabled={deletingId === item.id}
                  onClick={() => onDelete(item)}
                  type="button"
                >
                  <Trash2 size={15} />
                </button>
              </article>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}
