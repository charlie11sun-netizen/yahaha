"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, ExternalLink, Eye, EyeOff, Play, Trash2, Upload } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { api } from "@/lib/api";
import { coverBackgroundStyle, STUDIO_COVER_BACKGROUND } from "@/lib/cover";
import { useToast } from "@/lib/toast";
import type { Game, GameVersion } from "@/lib/types";
import { cn } from "@/lib/utils";
import { formatBytes } from "../_lib/studio-format";
import { EmptyState } from "./StudioPrimitives";

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
        <div
          aria-label={`Version ${version.version}`}
          className="grid gap-3 rounded-lg border border-slate-200 bg-white p-3 md:grid-cols-[1fr_auto_auto] md:items-center"
          key={version.version}
          role="group"
        >
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
