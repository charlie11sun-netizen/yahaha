"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Calendar,
  Database,
  GitFork,
  Heart,
  MessageCircle,
  Play,
  Share2,
  Star,
  Trash2,
  UserRound,
} from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { CSSProperties } from "react";

import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/toast";
import type { Comment, Game } from "@/lib/types";

function Centered({ children }: { children: React.ReactNode }) {
  return <div className="pf-state-page">{children}</div>;
}

export default function DetailPage() {
  const { id } = useParams() as { id: string };
  const router = useRouter();
  const { data: game, isError, isLoading } = useQuery({ queryKey: ["game", id], queryFn: () => api.game(id) });
  const { user } = useAuth();
  const flash = useToast();
  const queryClient = useQueryClient();
  const commentsQ = useQuery({ queryKey: ["comments", id], queryFn: () => api.comments(id) });
  const relatedQ = useQuery({ queryKey: ["related", id], queryFn: () => api.relatedGames(id) });
  const manifestQ = useQuery({ queryKey: ["manifest", id], queryFn: () => api.gameManifest(id) });
  const [commentText, setCommentText] = useState("");
  const [posting, setPosting] = useState(false);
  const [liked, setLiked] = useState(false);
  const [favorited, setFavorited] = useState(false);
  const [likes, setLikes] = useState(0);

  useEffect(() => {
    if (!game) return;
    setLiked(!!game.liked);
    setFavorited(!!game.favorited);
    setLikes(game.likes);
  }, [game]);

  if (isLoading) return <Centered>Loading game...</Centered>;
  if (isError || !game) return <Centered>Game not found.</Centered>;

  const requireUser = (message: string) => {
    if (user) return true;
    flash(message);
    router.push("/login");
    return false;
  };

  const toggleLike = () => {
    if (!requireUser("Sign in to like games")) return;
    if (liked) {
      setLiked(false);
      setLikes((value) => Math.max(0, value - 1));
      api.unlike(game.id).catch(() => {});
    } else {
      setLiked(true);
      setLikes((value) => value + 1);
      api.like(game.id).catch(() => {});
    }
  };

  const toggleFavorite = () => {
    if (!requireUser("Sign in to save favorites")) return;
    const next = !favorited;
    setFavorited(next);
    (next ? api.favorite(game.id) : api.unfavorite(game.id)).catch(() => {});
    queryClient.invalidateQueries({ queryKey: ["me-favorites"] });
  };

  const share = async () => {
    const url = window.location.href;
    try {
      if (navigator.share) await navigator.share({ title: game.title, url });
      else {
        await navigator.clipboard.writeText(url);
        flash("Link copied");
      }
    } catch {
      /* user cancelled */
    }
  };

  const remix = () => {
    if (!requireUser("Sign in to remix games")) return;
    const params = new URLSearchParams({
      remix: game.id,
      sourceTitle: game.title,
      idea: `Remix ${game.title} with a fresh mechanic and visual twist.`,
    });
    router.push(`/create?${params.toString()}`);
  };

  const postComment = async () => {
    if (!requireUser("Sign in to comment")) return;
    const body = commentText.trim();
    if (!body) return;
    try {
      setPosting(true);
      await api.addComment(game.id, body);
      setCommentText("");
      queryClient.invalidateQueries({ queryKey: ["comments", id] });
    } catch {
      flash("Could not post comment");
    } finally {
      setPosting(false);
    }
  };

  const removeComment = async (commentId: string) => {
    try {
      await api.deleteComment(game.id, commentId);
      queryClient.invalidateQueries({ queryKey: ["comments", id] });
    } catch {
      flash("Could not delete comment");
    }
  };

  return (
    <div className="pf-detail-page">
      <div className="pf-detail-shell">
        <button className="pf-back-link" onClick={() => router.push("/explore")} type="button">
          <ArrowLeft size={16} />
          Back to arcade
        </button>

        <section className="pf-detail-hero">
          <div className="pf-detail-media">
            <div className="pf-detail-cover" style={coverBackground(game.cover)}>
              <span>{game.genre}</span>
            </div>
            <button className="pf-detail-play" onClick={() => router.push(`/play/${game.id}`)} type="button">
              <Play size={18} fill="currentColor" />
              Play now
            </button>
          </div>

          <div className="pf-detail-copy">
            <h1>{game.title}</h1>
            <button className="pf-detail-author" onClick={() => router.push(`/users/${game.author_id}`)} type="button">
              <i>{game.author_init}</i>
              <span>{game.author}</span>
              <Calendar size={14} />
              <span>{game.date}</span>
            </button>

            <div className="pf-detail-actions">
              <button className={liked ? "is-active" : ""} onClick={toggleLike} type="button">
                <Heart size={16} fill={liked ? "currentColor" : "none"} />
                {likes}
              </button>
              <button className={favorited ? "is-active" : ""} onClick={toggleFavorite} type="button">
                <Star size={16} fill={favorited ? "currentColor" : "none"} />
                {favorited ? "Saved" : "Save"}
              </button>
              <button onClick={share} type="button">
                <Share2 size={16} />
                Share
              </button>
              <button onClick={remix} type="button">
                <GitFork size={16} />
                Remix
              </button>
            </div>

            <p>{game.summary}</p>

            <div className="pf-detail-tags">
              {(game.tags.length ? game.tags : [game.genre]).map((tag) => (
                <span key={tag}>#{tag}</span>
              ))}
            </div>

            <div className="pf-detail-stats">
              <DetailStat value={game.plays_str} label="plays" />
              <DetailStat value={game.likes_str} label="likes" />
              <DetailStat value={game.version} label="version" />
              <DetailStat value={String(game.remix_count ?? 0)} label="remixes" />
            </div>

            <div className="pf-detail-bundle">
              <Database size={16} />
              <div>
                <strong>Remote bundle</strong>
                <span>{game.oss_path}</span>
                {(manifestQ.data?.files?.length ?? 0) > 0 ? (
                  <div className="pf-detail-files">
                    {(manifestQ.data?.files ?? []).map((file) => (
                      <span className={file.path === (manifestQ.data?.entry || "index.html") ? "is-entry" : undefined} key={file.path}>
                        {file.path}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>

            {game.from_create && game.prompt ? (
              <div className="pf-detail-prompt">
                <strong>Generated from prompt</strong>
                <p>{game.prompt}</p>
              </div>
            ) : null}

            {game.remixed_from ? (
              <button
                className="pf-detail-remix-source"
                onClick={() => router.push(`/games/${game.remixed_from?.id}`)}
                type="button"
              >
                <GitFork size={16} />
                Remix of {game.remixed_from.title} by {game.remixed_from.author}
              </button>
            ) : null}
          </div>
        </section>

        <RelatedAndComments
          canModerate={(authorId) => !!user && (user.id === authorId || user.id === game.author_id)}
          commentText={commentText}
          comments={commentsQ.data?.items ?? []}
          onDelete={removeComment}
          onOpen={(relatedId) => router.push(`/games/${relatedId}`)}
          onPost={postComment}
          posting={posting}
          related={relatedQ.data?.items ?? []}
          setCommentText={setCommentText}
        />
      </div>
    </div>
  );
}

function RelatedAndComments({
  canModerate,
  commentText,
  comments,
  onDelete,
  onOpen,
  onPost,
  posting,
  related,
  setCommentText,
}: {
  canModerate: (authorId: string) => boolean;
  commentText: string;
  comments: Comment[];
  onDelete: (id: string) => void;
  onOpen: (id: string) => void;
  onPost: () => void;
  posting: boolean;
  related: Game[];
  setCommentText: (value: string) => void;
}) {
  return (
    <section className="pf-detail-lower">
      <div className="pf-detail-panel">
        <h2>
          <MessageCircle size={18} />
          Comments
        </h2>
        <div className="pf-comment-form">
          <input
            onChange={(event) => setCommentText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") onPost();
            }}
            placeholder="Add a comment..."
            value={commentText}
          />
          <button disabled={posting} onClick={onPost} type="button">
            {posting ? "Posting..." : "Post"}
          </button>
        </div>
        {comments.length === 0 ? (
          <p className="pf-detail-empty">No comments yet. Be the first.</p>
        ) : (
          <div className="pf-comment-list">
            {comments.map((comment) => (
              <article className="pf-comment-row" key={comment.id}>
                <span>{comment.author_init}</span>
                <div>
                  <strong>
                    {comment.author}
                    <i>{comment.ago}</i>
                  </strong>
                  <p>{comment.body}</p>
                </div>
                {canModerate(comment.author_id) ? (
                  <button aria-label="Delete comment" onClick={() => onDelete(comment.id)} type="button">
                    <Trash2 size={15} />
                  </button>
                ) : null}
              </article>
            ))}
          </div>
        )}
      </div>

      <div className="pf-detail-panel">
        <h2>
          <UserRound size={18} />
          Related games
        </h2>
        {related.length === 0 ? (
          <p className="pf-detail-empty">Nothing related yet.</p>
        ) : (
          <div className="pf-related-list">
            {related.slice(0, 5).map((game) => (
              <button key={game.id} onClick={() => onOpen(game.id)} type="button">
                <span style={coverBackground(game.cover)} />
                <div>
                  <strong>{game.title}</strong>
                  <i>{game.plays_str} plays</i>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function DetailStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function coverBackground(cover: string): CSSProperties {
  if (cover.startsWith("/") || cover.startsWith("http://") || cover.startsWith("https://")) {
    return { backgroundImage: `url("${cover}")` };
  }
  return { background: cover };
}
