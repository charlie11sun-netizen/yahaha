"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BadgeCheck,
  Brain,
  ChevronRight,
  ExternalLink,
  Eye,
  EyeOff,
  FileText,
  Gamepad2,
  House,
  KeyRound,
  Pencil,
  Play,
  Settings,
  Sparkles,
  Star,
  Trash2,
  Upload,
  User as UserIcon,
} from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import type { CSSProperties, ElementType, ReactNode } from "react";

import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmt } from "@/lib/format";
import { useToast } from "@/lib/toast";
import type { Game, MemoryItem, MemorySettings, Task } from "@/lib/types";

type Section = "overview" | "games" | "tasks" | "drafts" | "favorites" | "memory" | "settings";

const SECTIONS: { id: Section; label: string; icon: ElementType }[] = [
  { id: "overview", label: "Overview", icon: House },
  { id: "games", label: "My Games", icon: Gamepad2 },
  { id: "tasks", label: "Generation Tasks", icon: Sparkles },
  { id: "drafts", label: "Drafts", icon: FileText },
  { id: "favorites", label: "Favorites", icon: Star },
  { id: "memory", label: "Memory", icon: Brain },
  { id: "settings", label: "Account Settings", icon: Settings },
];

export default function ProfilePage() {
  return (
    <Suspense fallback={null}>
      <StudioPage />
    </Suspense>
  );
}

function StudioPage() {
  const { user, loading, setSession, logout } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const flash = useToast();
  const [section, setSection] = useState<Section>("overview");
  const [savingProfile, setSavingProfile] = useState(false);
  const [publishingId, setPublishingId] = useState<string | null>(null);
  const [busyGameId, setBusyGameId] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [changingPassword, setChangingPassword] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deletingTaskId, setDeletingTaskId] = useState<string | null>(null);
  const [newMemoryText, setNewMemoryText] = useState("");
  const [savingMemory, setSavingMemory] = useState(false);
  const [deletingMemoryId, setDeletingMemoryId] = useState<string | null>(null);
  const [savingMemorySettings, setSavingMemorySettings] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (user) {
      setDisplayName(user.name);
      setEmail(user.email);
    }
  }, [user]);

  useEffect(() => {
    const next = searchParams.get("section");
    if (isSection(next)) setSection(next);
  }, [searchParams]);

  const gamesQ = useQuery({ queryKey: ["me-games"], queryFn: api.myGames, enabled: !!user });
  const favQ = useQuery({ queryKey: ["me-favorites"], queryFn: api.myFavorites, enabled: !!user });
  const tasksQ = useQuery({ queryKey: ["tasks"], queryFn: api.tasks, enabled: !!user, refetchInterval: 3500 });
  const memoryQ = useQuery({ queryKey: ["memory"], queryFn: () => api.memories(), enabled: !!user });
  const memorySettingsQ = useQuery({ queryKey: ["memory-settings"], queryFn: api.memorySettings, enabled: !!user });

  const games = gamesQ.data?.items ?? [];
  const favorites = favQ.data?.items ?? [];
  const tasks = tasksQ.data?.items ?? [];
  const memories = memoryQ.data?.items ?? [];
  const memorySettings = memorySettingsQ.data;
  const published = useMemo(() => games.filter((game) => game.status === "published"), [games]);
  const drafts = useMemo(() => games.filter((game) => game.status !== "published"), [games]);
  const totalPlays = useMemo(() => games.reduce((sum, game) => sum + (game.plays || 0), 0), [games]);

  if (loading || !user) return null;

  const switchSection = (next: Section) => {
    setSection(next);
    const suffix = next === "overview" ? "/me" : `/me?section=${next}`;
    window.history.replaceState(null, "", suffix);
  };

  const invalidateGameLists = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ["me-games"] }),
      queryClient.invalidateQueries({ queryKey: ["games"] }),
      queryClient.invalidateQueries({ queryKey: ["stats"] }),
    ]);

  const publishGame = async (game: Game) => {
    try {
      setPublishingId(game.id);
      await api.publish(game.id);
      await invalidateGameLists();
      flash(`${game.title} published`);
    } catch (err) {
      flash(err instanceof Error ? err.message : "Publish failed");
    } finally {
      setPublishingId(null);
    }
  };

  const unpublishGame = async (game: Game) => {
    try {
      setBusyGameId(game.id);
      await api.unpublish(game.id);
      await invalidateGameLists();
      flash(`${game.title} unpublished`);
    } catch (err) {
      flash(err instanceof Error ? err.message : "Unpublish failed");
    } finally {
      setBusyGameId(null);
    }
  };

  const removeGame = async (game: Game) => {
    if (!window.confirm(`Delete "${game.title}"? This permanently removes the game and its bundle.`)) return;
    try {
      setBusyGameId(game.id);
      await api.deleteGame(game.id);
      await invalidateGameLists();
      flash(`${game.title} deleted`);
    } catch (err) {
      flash(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setBusyGameId(null);
    }
  };

  const saveProfile = async () => {
    const name = displayName.trim();
    if (!name) {
      flash("Display name is required");
      return;
    }
    try {
      setSavingProfile(true);
      const patch: { display_name?: string; email?: string } = { display_name: name };
      if (email.trim() && email.trim() !== user.email) patch.email = email.trim();
      const updated = await api.updateMe(patch);
      const token = localStorage.getItem("pf_token");
      if (token) setSession(token, updated);
      flash("Profile updated");
    } catch (err) {
      flash(err instanceof Error ? err.message : "Could not update profile");
    } finally {
      setSavingProfile(false);
    }
  };

  const setAvatar = async (avatar: string) => {
    try {
      const updated = await api.updateMe({ avatar });
      const token = localStorage.getItem("pf_token");
      if (token) setSession(token, updated);
      flash("Avatar updated");
    } catch {
      flash("Could not update avatar");
    }
  };

  const changePassword = async () => {
    if (newPassword.length < 6) {
      flash("New password must be at least 6 characters");
      return;
    }
    try {
      setChangingPassword(true);
      await api.changePassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      flash("Password updated");
    } catch (err) {
      flash(err instanceof Error ? err.message : "Could not change password");
    } finally {
      setChangingPassword(false);
    }
  };

  const deleteAccount = async () => {
    if (!window.confirm("Delete your account permanently? This removes your games, tasks, and data. This cannot be undone.")) return;
    try {
      setDeleting(true);
      await api.deleteAccount();
      logout();
      flash("Account deleted");
      router.push("/");
    } catch (err) {
      flash(err instanceof Error ? err.message : "Could not delete account");
      setDeleting(false);
    }
  };

  const removeTask = async (task: Task) => {
    if (!window.confirm("Delete this generation task? This permanently removes the task record.")) return;
    try {
      setDeletingTaskId(task.id);
      if (task.status === "pending" || task.status === "running") {
        await api.cancelTask(task.id);
      }
      await api.deleteTask(task.id);
      await queryClient.invalidateQueries({ queryKey: ["tasks"] });
      flash("Task deleted");
    } catch (err) {
      flash(err instanceof Error ? err.message : "Could not delete task");
    } finally {
      setDeletingTaskId(null);
    }
  };

  const openTask = (task: Task) => {
    if (task.status === "succeeded" && task.game) {
      router.push(`/play/${task.game.id}`);
      return;
    }
    localStorage.setItem("pf_last_create_task", task.id);
    router.push(`/create?task=${encodeURIComponent(task.id)}`);
  };

  const addMemory = async () => {
    const text = newMemoryText.trim();
    if (!text) {
      flash("Memory text is required");
      return;
    }
    try {
      setSavingMemory(true);
      await api.createMemory({
        scope_type: "user",
        category: "style",
        raw_text: text,
        importance: 4,
        pinned: true,
      });
      setNewMemoryText("");
      await queryClient.invalidateQueries({ queryKey: ["memory"] });
      flash("Memory saved");
    } catch (err) {
      flash(err instanceof Error ? err.message : "Could not save memory");
    } finally {
      setSavingMemory(false);
    }
  };

  const removeMemory = async (item: MemoryItem) => {
    try {
      setDeletingMemoryId(item.id);
      await api.deleteMemory(item.id);
      await queryClient.invalidateQueries({ queryKey: ["memory"] });
      flash("Memory deleted");
    } catch (err) {
      flash(err instanceof Error ? err.message : "Could not delete memory");
    } finally {
      setDeletingMemoryId(null);
    }
  };

  const updateMemorySettings = async (patch: Partial<MemorySettings>) => {
    try {
      setSavingMemorySettings(true);
      await api.updateMemorySettings(patch);
      await queryClient.invalidateQueries({ queryKey: ["memory-settings"] });
      flash("Memory settings updated");
    } catch (err) {
      flash(err instanceof Error ? err.message : "Could not update memory settings");
    } finally {
      setSavingMemorySettings(false);
    }
  };

  return (
    <div className="pf-studio-page">
      <div className="pf-studio-shell">
        <header className="pf-studio-header">
          <h1>My Studio</h1>
          <p>Manage your games, generation tasks, drafts, and account.</p>
        </header>

        <div className="pf-studio-grid">
          <aside className="pf-studio-sidebar">
            <div className="pf-studio-profile">
              <Avatar user={user} size="large" />
              <h2>{user.name}</h2>
              <span>Creator</span>
              <p>Joined {joinedDate(user.created_at)}</p>
            </div>

            <div className="pf-studio-actions">
              <button className="pf-studio-primary" onClick={() => router.push("/create")} type="button">
                <Upload size={16} />
                Create New Game
              </button>
              <button className="pf-studio-secondary" onClick={() => switchSection("settings")} type="button">
                <UserIcon size={16} />
                Edit Profile
              </button>
            </div>

            <nav className="pf-studio-side-nav" aria-label="Studio sections">
              {SECTIONS.map((item) => {
                const Icon = item.icon;
                return (
                  <button
                    className={section === item.id ? "is-active" : ""}
                    key={item.id}
                    onClick={() => switchSection(item.id)}
                    type="button"
                  >
                    <Icon size={20} />
                    {item.label}
                  </button>
                );
              })}
            </nav>
          </aside>

          <main className="pf-studio-main">
            <section className="pf-studio-stats">
              <StatCard icon={Gamepad2} label="Published Games" value={String(published.length)} />
              <StatCard icon={Pencil} label="Draft Games" value={String(drafts.length)} />
              <StatCard icon={Sparkles} label="Generation Tasks" value={String(tasks.length)} />
              <StatCard icon={Play} label="Total Plays" value={fmt(totalPlays)} />
            </section>

            {section === "overview" && (
              <>
                <Panel title="Recent Games" actionLabel="View all games" onAction={() => switchSection("games")}>
                  <GameGrid
                    emptyLabel={gamesQ.isLoading ? "Loading games..." : "No games yet"}
                    games={games.slice(0, 3)}
                    onDelete={removeGame}
                    onPublish={publishGame}
                    onUnpublish={unpublishGame}
                    publishingId={publishingId}
                    busyId={busyGameId}
                  />
                </Panel>

                <Panel title="Recent Generation Tasks" actionLabel="View all tasks" onAction={() => switchSection("tasks")}>
                  <TaskTable
                    deletingId={deletingTaskId}
                    emptyLabel={tasksQ.isLoading ? "Loading tasks..." : "No generation tasks yet"}
                    onDelete={removeTask}
                    onOpen={openTask}
                    tasks={tasks.slice(0, 4)}
                  />
                </Panel>
              </>
            )}

            {section === "games" && (
              <Panel title="My Games" actionLabel="Create game" onAction={() => router.push("/create")}>
                <GameGrid
                  emptyLabel={gamesQ.isLoading ? "Loading games..." : "No games yet"}
                  games={games}
                  onDelete={removeGame}
                  onPublish={publishGame}
                  onUnpublish={unpublishGame}
                  publishingId={publishingId}
                  busyId={busyGameId}
                />
              </Panel>
            )}

            {section === "drafts" && (
              <Panel title="Draft Games" actionLabel="Create game" onAction={() => router.push("/create")}>
                <GameGrid
                  emptyLabel={gamesQ.isLoading ? "Loading drafts..." : "No draft games yet"}
                  games={drafts}
                  onDelete={removeGame}
                  onPublish={publishGame}
                  onUnpublish={unpublishGame}
                  publishingId={publishingId}
                  busyId={busyGameId}
                />
              </Panel>
            )}

            {section === "favorites" && (
              <Panel title="Favorites" actionLabel="Explore games" onAction={() => router.push("/")}>
                <GameGrid
                  emptyLabel={favQ.isLoading ? "Loading favorites..." : "No favorites yet"}
                  games={favorites}
                  onPublish={publishGame}
                  publishingId={publishingId}
                  readonly
                />
              </Panel>
            )}

            {section === "tasks" && (
              <Panel title="Generation Tasks" actionLabel="Create game" onAction={() => router.push("/create")}>
                <TaskTable
                  deletingId={deletingTaskId}
                  emptyLabel={tasksQ.isLoading ? "Loading tasks..." : "No generation tasks yet"}
                  onDelete={removeTask}
                  onOpen={openTask}
                  tasks={tasks}
                />
              </Panel>
            )}

            {section === "memory" && (
              <MemorySection
                deletingId={deletingMemoryId}
                items={memories}
                loading={memoryQ.isLoading || memorySettingsQ.isLoading}
                newMemoryText={newMemoryText}
                onAdd={addMemory}
                onDelete={removeMemory}
                onTextChange={setNewMemoryText}
                onUpdateSettings={updateMemorySettings}
                saving={savingMemory}
                savingSettings={savingMemorySettings}
                settings={memorySettings}
              />
            )}

            {section === "settings" && (
              <div className="pf-studio-settings pf-studio-settings-layout">
                <Panel title="Public profile">
                  <div className="pf-studio-settings-card">
                    <Avatar user={user} size="medium" />
                    <div>
                      <h3>{user.name}</h3>
                      <p>Your public creator identity is used across published games, comments, and playable results.</p>
                    </div>
                  </div>

                  <div className="pf-studio-field-grid">
                    <label className="pf-studio-field">
                      <span>Display name</span>
                      <input maxLength={120} onChange={(event) => setDisplayName(event.target.value)} value={displayName} />
                    </label>
                    <label className="pf-studio-field">
                      <span>Email</span>
                      <input onChange={(event) => setEmail(event.target.value)} type="email" value={email} />
                    </label>
                  </div>

                  <div className="pf-avatar-palette">
                    <span>Avatar mark</span>
                    <div>
                      {avatarChoices(user.name).map((mark) => (
                        <button
                          className={user.init === mark ? "is-selected" : ""}
                          key={mark}
                          onClick={() => setAvatar(mark)}
                          type="button"
                        >
                          {mark}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="pf-studio-settings-actions">
                    <button className="pf-studio-primary" disabled={savingProfile} onClick={saveProfile} type="button">
                      <BadgeCheck size={16} />
                      {savingProfile ? "Saving..." : "Save Profile"}
                    </button>
                  </div>
                </Panel>

                <div className="pf-studio-settings-side">
                  <Panel title="Change password">
                    <label className="pf-studio-field">
                      <span>Current password</span>
                      <input
                        onChange={(event) => setCurrentPassword(event.target.value)}
                        placeholder="Required for password accounts"
                        type="password"
                        value={currentPassword}
                      />
                    </label>
                    <label className="pf-studio-field">
                      <span>New password</span>
                      <input onChange={(event) => setNewPassword(event.target.value)} type="password" value={newPassword} />
                    </label>
                    <div className="pf-studio-settings-actions">
                      <button className="pf-studio-secondary" disabled={changingPassword} onClick={changePassword} type="button">
                        <KeyRound size={16} />
                        {changingPassword ? "Updating..." : "Update password"}
                      </button>
                    </div>
                  </Panel>

                  <Panel title="Danger zone">
                    <p className="pf-danger-copy">
                      Deleting your account permanently removes your games, generation tasks, and data. This cannot be undone.
                    </p>
                    <div className="pf-studio-settings-actions">
                      <button className="pf-danger-btn" disabled={deleting} onClick={deleteAccount} type="button">
                        <Trash2 size={16} />
                        {deleting ? "Deleting..." : "Delete account"}
                      </button>
                    </div>
                  </Panel>
                </div>
              </div>
            )}
          </main>
        </div>
      </div>
    </div>
  );
}

function StatCard({ icon: Icon, label, value }: { icon: ElementType; label: string; value: string }) {
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

function Panel({
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

function GameGrid({
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
  const isPublished = game.status === "published";

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
      </div>
    </article>
  );
}

function TaskTable({
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

function MemorySection({
  deletingId,
  items,
  loading,
  newMemoryText,
  onAdd,
  onDelete,
  onTextChange,
  onUpdateSettings,
  saving,
  savingSettings,
  settings,
}: {
  deletingId: string | null;
  items: MemoryItem[];
  loading: boolean;
  newMemoryText: string;
  onAdd: () => void;
  onDelete: (item: MemoryItem) => void;
  onTextChange: (value: string) => void;
  onUpdateSettings: (patch: Partial<MemorySettings>) => void;
  saving: boolean;
  savingSettings: boolean;
  settings?: MemorySettings;
}) {
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

function Avatar({ size, user }: { size: "large" | "medium"; user: { init: string; name: string } }) {
  return (
    <div aria-label={user.name} className={`pf-studio-avatar is-${size}`}>
      {user.init}
    </div>
  );
}

function avatarChoices(name: string) {
  const initial = (name.trim().slice(0, 1) || "A").toUpperCase();
  return Array.from(new Set([initial, "AI", "PF", "XP", "01", "GG"]));
}

function coverStyle(cover?: string): CSSProperties {
  if (!cover) {
    return {
      background: "linear-gradient(135deg, #101844, #4f7dff 52%, #8be8f1)",
    };
  }
  if (cover.startsWith("/") || cover.startsWith("http://") || cover.startsWith("https://")) {
    return { backgroundImage: `url("${cover}")` };
  }
  return { background: cover };
}

function joinedDate(value?: string | null) {
  if (!value) return "Recently";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Recently";
  return new Intl.DateTimeFormat("en", { month: "long", year: "numeric" }).format(date);
}

function shortId(id: string) {
  return `GEN-${id.replace(/-/g, "").slice(0, 4).toUpperCase()}`;
}

function taskStatusLabel(status: string) {
  if (status === "succeeded") return "Succeeded";
  if (status === "running") return "Running";
  if (status === "failed") return "Failed";
  if (status === "cancelled") return "Cancelled";
  return "Pending";
}

function taskActionLabel(task: Task) {
  if (task.status === "succeeded" && task.game) return "Open Result";
  if (task.status === "failed") return "View Logs";
  return "View Activity";
}

function taskStep(task: Task) {
  if (task.status === "succeeded") return "Preview ready";
  if (task.status === "failed") return "Validation failed";
  const running = task.step_summaries?.find((step) => step.status === "running");
  const lastDone = [...(task.step_summaries ?? [])].reverse().find((step) => step.status === "completed");
  return running?.title || lastDone?.title || "Queued";
}

function memoryScopeLabel(item: MemoryItem) {
  if (item.scope_type === "game") return `Game ${item.source_version || ""}`.trim();
  if (item.scope_type === "task") return "Task";
  return item.pinned ? "User preference · pinned" : "User preference";
}

function memoryDate(value?: string | null) {
  if (!value) return "recently";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "recently";
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric" }).format(date);
}

function isSection(value: string | null): value is Section {
  return value === "overview" || value === "games" || value === "tasks" || value === "drafts" || value === "favorites" || value === "memory" || value === "settings";
}
