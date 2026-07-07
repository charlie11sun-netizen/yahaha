"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  BadgeCheck,
  Brain,
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
import type { ElementType } from "react";

import {
  Avatar,
  GameGrid,
  MemorySection,
  Panel,
  StatCard,
  TaskTable,
} from "./_components/StudioPanels";
import { isSection, type Section } from "./_lib/studio-state";
import { useStudioQueries } from "./_lib/use-studio-queries";
import { avatarChoices, joinedDate } from "./_lib/studio-format";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmt } from "@/lib/format";
import { useToast } from "@/lib/toast";
import type { Game, MemoryItem, MemoryProfile, MemorySettings, Task } from "@/lib/types";

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
  const [profileActionId, setProfileActionId] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && !user) router.replace("/login?next=/me");
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

  const { gamesQ, favQ, tasksQ, memoryQ, memoryProfilesQ, memorySettingsQ } = useStudioQueries(!!user);

  const games = gamesQ.data?.items ?? [];
  const favorites = favQ.data?.items ?? [];
  const tasks = tasksQ.data?.items ?? [];
  const memories = memoryQ.data?.items ?? [];
  const memoryProfiles = memoryProfilesQ.data?.items ?? [];
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
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["memory"] }),
        queryClient.invalidateQueries({ queryKey: ["memory-profiles"] }),
      ]);
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
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["memory"] }),
        queryClient.invalidateQueries({ queryKey: ["memory-profiles"] }),
      ]);
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

  const editMemoryProfile = async (profile: MemoryProfile) => {
    const summary = window.prompt("Correct this active memory", profile.summary_text)?.trim();
    if (!summary || summary === profile.summary_text) return;
    try {
      setProfileActionId(profile.id);
      await api.updateMemoryProfile(profile.id, { summary_text: summary });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["memory"] }),
        queryClient.invalidateQueries({ queryKey: ["memory-profiles"] }),
      ]);
      flash("Memory profile corrected");
    } catch (err) {
      flash(err instanceof Error ? err.message : "Could not correct memory profile");
    } finally {
      setProfileActionId(null);
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
                    emptyLabel={gamesQ.isLoading ? "Loading games..." : gamesQ.isError ? "Could not load games — try refreshing" : "No games yet"}
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
                    emptyLabel={tasksQ.isLoading ? "Loading tasks..." : tasksQ.isError ? "Could not load tasks — try refreshing" : "No generation tasks yet"}
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
                  emptyLabel={gamesQ.isLoading ? "Loading games..." : gamesQ.isError ? "Could not load games — try refreshing" : "No games yet"}
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
                  emptyLabel={gamesQ.isLoading ? "Loading drafts..." : gamesQ.isError ? "Could not load games — try refreshing" : "No draft games yet"}
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
              <Panel title="Favorites" actionLabel="Explore games" onAction={() => router.push("/explore")}>
                <GameGrid
                  emptyLabel={favQ.isLoading ? "Loading favorites..." : favQ.isError ? "Could not load favorites — try refreshing" : "No favorites yet"}
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
                  emptyLabel={tasksQ.isLoading ? "Loading tasks..." : tasksQ.isError ? "Could not load tasks — try refreshing" : "No generation tasks yet"}
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
                loading={memoryQ.isLoading || memoryProfilesQ.isLoading || memorySettingsQ.isLoading}
                newMemoryText={newMemoryText}
                onAdd={addMemory}
                onDelete={removeMemory}
                onEditProfile={editMemoryProfile}
                onTextChange={setNewMemoryText}
                onUpdateSettings={updateMemorySettings}
                saving={savingMemory}
                savingSettings={savingMemorySettings}
                settings={memorySettings}
                profileActionId={profileActionId}
                profiles={memoryProfiles}
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
