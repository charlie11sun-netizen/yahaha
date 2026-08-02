"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageCircle, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/toast";
import type { Comment } from "@/lib/types";

export function GameComments({
  gameAuthorId,
  gameId,
  initialComments,
}: {
  gameAuthorId: string;
  gameId: string;
  initialComments: Comment[];
}) {
  const { user } = useAuth();
  const router = useRouter();
  const flash = useToast();
  const queryClient = useQueryClient();
  const [commentText, setCommentText] = useState("");
  const [posting, setPosting] = useState(false);
  const commentsQuery = useQuery({
    queryKey: ["comments", gameId],
    queryFn: () => api.comments(gameId),
    initialData: { items: initialComments },
    staleTime: 30_000,
  });

  const requireUser = () => {
    if (user) return true;
    flash("Sign in to comment");
    router.push(`/login?next=${encodeURIComponent(`/games/${gameId}`)}`);
    return false;
  };

  const postComment = async () => {
    if (!requireUser()) return;
    const body = commentText.trim();
    if (!body) return;
    try {
      setPosting(true);
      await api.addComment(gameId, body);
      setCommentText("");
      await queryClient.invalidateQueries({ queryKey: ["comments", gameId] });
    } catch {
      flash("Could not post comment");
    } finally {
      setPosting(false);
    }
  };

  const removeComment = async (commentId: string) => {
    try {
      await api.deleteComment(gameId, commentId);
      await queryClient.invalidateQueries({ queryKey: ["comments", gameId] });
    } catch {
      flash("Could not delete comment");
    }
  };

  const comments = commentsQuery.data.items;
  return (
    <Card className="rounded-lg border-slate-200/80 bg-white/90 shadow-sm">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 font-display text-xl tracking-normal text-slate-950">
          <MessageCircle size={18} />Comments
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="flex gap-3">
          <Input
            onChange={(event) => setCommentText(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Enter") void postComment(); }}
            placeholder="Add a comment..."
            value={commentText}
          />
          <Button className="rounded-lg" disabled={posting} onClick={postComment} type="button">
            {posting ? "Posting..." : "Post"}
          </Button>
        </div>
        {comments.length === 0 ? (
          <p className="rounded-lg border border-dashed border-slate-200 bg-slate-50 p-6 text-center text-sm text-slate-500">No comments yet. Be the first.</p>
        ) : (
          <div className="space-y-3">
            {comments.map((comment) => (
              <article className="flex gap-3 rounded-lg border border-slate-200 bg-white p-4" key={comment.id}>
                <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-sm font-semibold text-white">{comment.author_init}</span>
                <div className="min-w-0 flex-1">
                  <strong className="flex flex-wrap items-center gap-2 text-sm font-semibold text-slate-950">
                    {comment.author}<i className="text-xs font-medium not-italic text-slate-500">{comment.ago}</i>
                  </strong>
                  <p className="mt-1 text-sm leading-6 text-slate-600">{comment.body}</p>
                </div>
                {user && (user.id === comment.author_id || user.id === gameAuthorId) ? (
                  <Button aria-label="Delete comment" onClick={() => removeComment(comment.id)} size="icon" type="button" variant="ghost"><Trash2 size={15} /></Button>
                ) : null}
              </article>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
