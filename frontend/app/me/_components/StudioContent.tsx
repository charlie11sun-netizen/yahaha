"use client";

import { MemorySection } from "./StudioPanels";
import {
  StudioDraftsSection,
  StudioFavoritesSection,
  StudioGamesSection,
  StudioOverviewSection,
  StudioTasksSection,
} from "./StudioGameSections";
import { StudioSettingsSection } from "./StudioSettingsSection";
import type { StudioController } from "../_lib/use-studio-controller";

export function StudioContent({ studio }: { studio: StudioController }) {
  const {
    addMemory,
    deletingMemoryId,
    editMemoryProfile,
    memoryProfiles,
    memoryProfilesQ,
    memoryQ,
    memorySettings,
    memorySettingsQ,
    memories,
    newMemoryText,
    profileActionId,
    removeMemory,
    savingMemory,
    savingMemorySettings,
    section,
    setNewMemoryText,
    updateMemorySettings,
  } = studio;

  if (section === "overview") return <StudioOverviewSection studio={studio} />;
  if (section === "games") return <StudioGamesSection studio={studio} />;
  if (section === "drafts") return <StudioDraftsSection studio={studio} />;
  if (section === "favorites") return <StudioFavoritesSection studio={studio} />;
  if (section === "tasks") return <StudioTasksSection studio={studio} />;

  if (section === "memory") {
    return (
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
    );
  }

  return <StudioSettingsSection studio={studio} />;
}
