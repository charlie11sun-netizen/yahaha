"use client";

import { GameGrid, Panel, TaskTable } from "./StudioPanels";
import type { StudioController } from "../_lib/use-studio-controller";

export function StudioOverviewSection({ studio }: { studio: StudioController }) {
  const {
    busyGameId,
    deletingTaskId,
    games,
    gamesQ,
    openTask,
    publishGame,
    publishingId,
    removeGame,
    removeTask,
    switchSection,
    tasks,
    tasksQ,
    unpublishGame,
  } = studio;

  return (
    <>
      <Panel title="Recent Games" actionLabel="View all games" onAction={() => switchSection("games")}>
        <GameGrid
          emptyLabel={gamesQ.isLoading ? "Loading games..." : gamesQ.isError ? "Could not load games - try refreshing" : "No games yet"}
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
          emptyLabel={tasksQ.isLoading ? "Loading tasks..." : tasksQ.isError ? "Could not load tasks - try refreshing" : "No generation tasks yet"}
          onDelete={removeTask}
          onOpen={openTask}
          tasks={tasks.slice(0, 4)}
        />
      </Panel>
    </>
  );
}

export function StudioGamesSection({ studio }: { studio: StudioController }) {
  const { busyGameId, games, gamesQ, publishGame, publishingId, removeGame, router, unpublishGame } = studio;

  return (
    <Panel title="My Games" actionLabel="Create game" onAction={() => router.push("/create")}>
      <GameGrid
        emptyLabel={gamesQ.isLoading ? "Loading games..." : gamesQ.isError ? "Could not load games - try refreshing" : "No games yet"}
        games={games}
        onDelete={removeGame}
        onPublish={publishGame}
        onUnpublish={unpublishGame}
        publishingId={publishingId}
        busyId={busyGameId}
      />
    </Panel>
  );
}

export function StudioDraftsSection({ studio }: { studio: StudioController }) {
  const { busyGameId, drafts, gamesQ, publishGame, publishingId, removeGame, router, unpublishGame } = studio;

  return (
    <Panel title="Draft Games" actionLabel="Create game" onAction={() => router.push("/create")}>
      <GameGrid
        emptyLabel={gamesQ.isLoading ? "Loading drafts..." : gamesQ.isError ? "Could not load games - try refreshing" : "No draft games yet"}
        games={drafts}
        onDelete={removeGame}
        onPublish={publishGame}
        onUnpublish={unpublishGame}
        publishingId={publishingId}
        busyId={busyGameId}
      />
    </Panel>
  );
}

export function StudioFavoritesSection({ studio }: { studio: StudioController }) {
  const { favQ, favorites, publishGame, publishingId, router } = studio;

  return (
    <Panel title="Favorites" actionLabel="Explore games" onAction={() => router.push("/explore")}>
      <GameGrid
        emptyLabel={favQ.isLoading ? "Loading favorites..." : favQ.isError ? "Could not load favorites - try refreshing" : "No favorites yet"}
        games={favorites}
        onPublish={publishGame}
        publishingId={publishingId}
        readonly
      />
    </Panel>
  );
}

export function StudioTasksSection({ studio }: { studio: StudioController }) {
  const { deletingTaskId, openTask, removeTask, router, tasks, tasksQ } = studio;

  return (
    <Panel title="Generation Tasks" actionLabel="Create game" onAction={() => router.push("/create")}>
      <TaskTable
        deletingId={deletingTaskId}
        emptyLabel={tasksQ.isLoading ? "Loading tasks..." : tasksQ.isError ? "Could not load tasks - try refreshing" : "No generation tasks yet"}
        onDelete={removeTask}
        onOpen={openTask}
        tasks={tasks}
      />
    </Panel>
  );
}
