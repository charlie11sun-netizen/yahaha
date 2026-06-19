"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BadgeCheck,
  ChevronRight,
  ExternalLink,
  Eye,
  FileText,
  Gamepad2,
  House,
  Pencil,
  Play,
  Rocket,
  Settings,
  Sparkles,
  Star,
  Upload,
  User as UserIcon,
} from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";

import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmt } from "@/lib/format";
import { useToast } from "@/lib/toast";
import type { Game, Task } from "@/lib/types";

type Section = "overview" | "games" | "tasks" | "drafts" | "favorites" | "settings";

const SECTIONS: { id: Section; label: string; icon: React.ElementType }[] = [
  { id: "overview", label: "Overview", icon: House },
  { id: "games", label: "My Games", icon: Gamepad2 },
  { id: "tasks", label: "Generation Tasks", icon: Sparkles },
  { id: "drafts", label: "Drafts", icon: FileText },
  { id: "favorites", label: "Favorites", icon: Star },
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
  const { user, loading, setSession } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const flash = useToast();
  const [section, setSection] = useState<Section>("overview");
  const [savingProfile, setSavingProfile] = useState(false);
  const [publishingId, setPublishingId] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState("");

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (user) setDisplayName(user.name);
  }, [user]);

  useEffect(() => {
    const next = searchParams.get("section");
    if (isSection(next)) setSection(next);
  }, [searchParams]);

  const gamesQ = useQuery({ queryKey: ["me-games"], queryFn: api.myGames, enabled: !!user });
  const favQ = useQuery({ queryKey: ["me-favorites"], queryFn: api.myFavorites, enabled: !!user });
  const tasksQ = useQuery({ queryKey: ["tasks"], queryFn: api.tasks, enabled: !!user, refetchInterval: 3500 });

  const games = gamesQ.data?.items ?? [];
  const favorites = favQ.data?.items ?? [];
  const tasks = tasksQ.data?.items ?? [];

  const published = useMemo(() => games.filter((game) => game.status === "published"), [games]);
  const drafts = useMemo(() => games.filter((game) => game.status !== "published"), [games]);
  const totalPlays = useMemo(() => games.reduce((sum, game) => sum + (game.plays || 0), 0), [games]);

  if (loading || !user) return null;

  const switchSection = (next: Section) => {
    setSection(next);
    const suffix = next === "overview" ? "/me" : `/me?section=${next}`;
    window.history.replaceState(null, "", suffix);
  };

  const publishGame = async (game: Game) => {
    try {
      setPublishingId(game.id);
      await api.publish(game.id);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["me-games"] }),
        queryClient.invalidateQueries({ queryKey: ["games"] }),
        queryClient.invalidateQueries({ queryKey: ["stats"] }),
      ]);
      flash(`${game.title} published`);
    } catch (err) {
      flash(err instanceof Error ? err.message : "Publish failed");
    } finally {
      setPublishingId(null);
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
      const updated = await api.updateMe(name);
      const token = localStorage.getItem("pf_token");
      if (token) setSession(token, updated);
      flash("Profile updated");
    } catch (err) {
      flash(err instanceof Error ? err.message : "Could not update profile");
    } finally {
      setSavingProfile(false);
    }
  };

  const openTask = (task: Task) => {
    localStorage.setItem("pf_last_create_task", task.id);
    router.push("/create");
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
                <Panel
                  title="Recent Games"
                  actionLabel="View all games"
                  onAction={() => switchSection("games")}
                >
                  <GameGrid
                    emptyLabel={gamesQ.isLoading ? "Loading games..." : "No games yet"}
                    games={games.slice(0, 3)}
                    onPublish={publishGame}
                    publishingId={publishingId}
                  />
                </Panel>

                <Panel
                  title="Recent Generation Tasks"
                  actionLabel="View all tasks"
                  onAction={() => switchSection("tasks")}
                >
                  <TaskTable
                    emptyLabel={tasksQ.isLoading ? "Loading tasks..." : "No generation tasks yet"}
                    tasks={tasks.slice(0, 4)}
                    onOpen={openTask}
                  />
                </Panel>
              </>
            )}

            {section === "games" && (
              <Panel title="My Games" actionLabel="Create game" onAction={() => router.push("/create")}>
                <GameGrid
                  emptyLabel={gamesQ.isLoading ? "Loading games..." : "No games yet"}
                  games={games}
                  onPublish={publishGame}
                  publishingId={publishingId}
                />
              </Panel>
            )}

            {section === "drafts" && (
              <Panel title="Draft Games" actionLabel="Create game" onAction={() => router.push("/create")}>
                <GameGrid
                  emptyLabel={gamesQ.isLoading ? "Loading drafts..." : "No draft games yet"}
                  games={drafts}
                  onPublish={publishGame}
                  publishingId={publishingId}
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
                  emptyLabel={tasksQ.isLoading ? "Loading tasks..." : "No generation tasks yet"}
                  tasks={tasks}
                  onOpen={openTask}
                />
              </Panel>
            )}

            {section === "settings" && (
              <Panel title="Account Settings">
                <div className="pf-studio-settings">
                  <div className="pf-studio-settings-card">
                    <Avatar user={user} size="medium" />
                    <div>
                      <h3>Public profile</h3>
                      <p>This name appears on your published games and generated previews.</p>
                    </div>
                  </div>

                  <label className="pf-studio-field">
                    <span>Display name</span>
                    <input
                      maxLength={120}
                      onChange={(event) => setDisplayName(event.target.value)}
                      value={displayName}
                    />
                  </label>

                  <div className="pf-studio-settings-actions">
                    <button className="pf-studio-primary" disabled={savingProfile} onClick={saveProfile} type="button">
                      <BadgeCheck size={16} />
                      {savingProfile ? "Saving..." : "Save Profile"}
                    </button>
                  </div>
                </div>
              </Panel>
            )}
          </main>
        </div>
      </div>
    </div>
  );
}

function StatCard({ icon: Icon, label, value }: { icon: React.ElementType; label: string; value: string }) {
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
  children: React.ReactNode;
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
  publishingId,
  readonly = false,
}: {
  emptyLabel: string;
  games: Game[];
  onPublish: (game: Game) => void;
  publishingId: string | null;
  readonly?: boolean;
}) {
  if (games.length === 0) {
    return <div className="pf-studio-empty">{emptyLabel}</div>;
  }

  return (
    <div className="pf-studio-game-grid">
      {games.map((game) => (
        <StudioGameCard
          game={game}
          key={game.id}
          onPublish={onPublish}
          publishing={publishingId === game.id}
          readonly={readonly}
        />
      ))}
    </div>
  );
}

function StudioGameCard({
  game,
  onPublish,
  publishing,
  readonly,
}: {
  game: Game;
  onPublish: (game: Game) => void;
  publishing: boolean;
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
          <button onClick={() => router.push(`/play/${game.id}`)} type="button">
            {isPublished ? <Play size={15} /> : <Eye size={15} />}
            {isPublished ? "Play" : "Preview"}
          </button>
          {isPublished || readonly ? (
            <button className="is-muted" onClick={() => router.push(`/games/${game.id}`)} type="button">
              View on Home
              <ExternalLink size={14} />
            </button>
          ) : (
            <button
              className="is-primary"
              disabled={publishing}
              onClick={() => onPublish(game)}
              type="button"
            >
              <Upload size={15} />
              {publishing ? "Publishing..." : "Publish"}
            </button>
          )}
        </div>
      </div>
    </article>
  );
}

function TaskTable({
  emptyLabel,
  onOpen,
  tasks,
}: {
  emptyLabel: string;
  onOpen: (task: Task) => void;
  tasks: Task[];
}) {
  if (tasks.length === 0) {
    return <div className="pf-studio-empty">{emptyLabel}</div>;
  }

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
          <button onClick={() => onOpen(task)} type="button">
            {taskActionLabel(task)}
            <ChevronRight size={17} />
          </button>
        </div>
      ))}
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

function isSection(value: string | null): value is Section {
  return value === "overview" || value === "games" || value === "tasks" || value === "drafts" || value === "favorites" || value === "settings";
}
