"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { isSection, type Section } from "./studio-state";
import { useStudioQueries } from "./use-studio-queries";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/toast";
import type { Game, MemoryItem, MemoryProfile, MemorySettings, Task } from "@/lib/types";

export function useStudioController() {

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

  const games = useMemo(() => gamesQ.data?.items ?? [], [gamesQ.data?.items]);
  const favorites = favQ.data?.items ?? [];
  const tasks = tasksQ.data?.items ?? [];
  const memories = memoryQ.data?.items ?? [];
  const memoryProfiles = memoryProfilesQ.data?.items ?? [];
  const memorySettings = memorySettingsQ.data;
  const published = useMemo(() => games.filter((game) => game.status === "published"), [games]);
  const drafts = useMemo(() => games.filter((game) => game.status !== "published"), [games]);
  const totalPlays = useMemo(() => games.reduce((sum, game) => sum + (game.plays || 0), 0), [games]);
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
      if (email.trim() && email.trim() !== user?.email) patch.email = email.trim();
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

  if (loading || !user) return { ready: false as const };

  return {
    ready: true as const,
    user,
    router,
    section,
    gamesQ,
    favQ,
    tasksQ,
    memoryQ,
    memoryProfilesQ,
    memorySettingsQ,
    games,
    favorites,
    tasks,
    memories,
    memoryProfiles,
    memorySettings,
    published,
    drafts,
    totalPlays,
    savingProfile,
    publishingId,
    busyGameId,
    displayName,
    email,
    currentPassword,
    newPassword,
    changingPassword,
    deleting,
    deletingTaskId,
    newMemoryText,
    savingMemory,
    deletingMemoryId,
    savingMemorySettings,
    profileActionId,
    setDisplayName,
    setEmail,
    setCurrentPassword,
    setNewPassword,
    setNewMemoryText,
    switchSection,
    publishGame,
    unpublishGame,
    removeGame,
    saveProfile,
    setAvatar,
    changePassword,
    deleteAccount,
    removeTask,
    openTask,
    addMemory,
    removeMemory,
    updateMemorySettings,
    editMemoryProfile,
  };
}

export type StudioController = Extract<ReturnType<typeof useStudioController>, { ready: true }>;
