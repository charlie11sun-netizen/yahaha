import type { components } from "./api-types";

type Schemas = components["schemas"];
type GameCard = Schemas["GameCardOut"];
type GameDetail = Schemas["GameDetailOut"];

export type User = Schemas["UserOut"];
export type OAuthProviders = Schemas["OAuthProvidersOut"];

// Frontend views intentionally accept both list cards and detail payloads.
// Endpoint-specific response types remain available below for tighter callers.
export type Game = GameCard & Partial<Omit<GameDetail, keyof GameCard>>;
export type GameDetailResponse = GameDetail;
export type GameListResponse = Schemas["GameListOut"];
export type GameCollectionResponse = Schemas["GameCollectionOut"];
export type GameVersion = Schemas["GameVersionOut"];
export type GameVersionListResponse = Schemas["GameVersionListOut"];
export type GameManifestFile = Schemas["GameManifestFileOut"];
export type GameManifest = Schemas["GameManifestOut"];

export type Step = Schemas["TaskStepOut"];
export type StepSummary = Schemas["TaskStepSummaryOut"];
export type AgentLogItem = Schemas["AgentLogItemOut"];
export type AgentLogEvent = NonNullable<Schemas["AgentLogEntryOut"]["event"]>;
export type AgentLogEntry = Schemas["AgentLogEntryOut"];
export type DesignPreview = Schemas["DesignPreviewOut"];
export type TaskAsset = Schemas["TaskAssetOut"];
export type Task = Schemas["TaskOut"];
export type TaskListResponse = Schemas["TaskListOut"];
export type TaskIdResponse = Schemas["TaskIdOut"];
export type TaskRetryResponse = Schemas["TaskRetryOut"];

export type AgentBundleFile = Schemas["AgentBundleFileOut"];
export type AgentFileContext = Schemas["AgentFileContextOut"];
export type AgentBundleMetadata = Schemas["AgentBundleMetadataOut"];

export type UploadedAsset = Schemas["UploadedAssetOut"];
export type UploadResponse = Schemas["UploadOut"];
export type Comment = Schemas["CommentOut"];
export type CommentListResponse = Schemas["CommentListOut"];
export type PublicUserProfile = Schemas["PublicUserProfileOut"];
export type TagsResponse = Schemas["TagsOut"];
export type MemoryItem = Schemas["MemoryItemOut"];
export type MemoryListResponse = Schemas["MemoryListOut"];
export type MemorySettings = Schemas["MemorySettingsOut"];
export type MemoryProfile = Schemas["MemoryProfileOut"];
export type MemoryProfileListResponse = Schemas["MemoryProfileListOut"];
export type MemoryProfileVersion = Schemas["MemoryProfileVersionOut"];
export type MemoryProfileHistoryResponse = Schemas["MemoryProfileHistoryOut"];
