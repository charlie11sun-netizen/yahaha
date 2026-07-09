import { MessageCircle, Trash2, UserRound } from "lucide-react";
import type { ReactNode } from "react";

import { StatusPage } from "@/app/_components/StatusPage";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { coverBackgroundStyle } from "@/lib/cover";
import type { Comment, Game } from "@/lib/types";

export function Centered({ children }: { children: ReactNode }) {
  return <StatusPage>{children}</StatusPage>;
}

export function RelatedAndComments({
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
    <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
      <Card className="rounded-lg border-slate-200/80 bg-white/90 shadow-sm">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 font-display text-xl tracking-normal text-slate-950">
            <MessageCircle size={18} />
            Comments
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="flex gap-3">
            <Input
              onChange={(event) => setCommentText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") onPost();
              }}
              placeholder="Add a comment..."
              value={commentText}
            />
            <Button className="rounded-lg" disabled={posting} onClick={onPost} type="button">
              {posting ? "Posting..." : "Post"}
            </Button>
          </div>
          {comments.length === 0 ? (
            <p className="rounded-lg border border-dashed border-slate-200 bg-slate-50 p-6 text-center text-sm text-slate-500">
              No comments yet. Be the first.
            </p>
          ) : (
            <div className="space-y-3">
              {comments.map((comment) => (
                <article className="flex gap-3 rounded-lg border border-slate-200 bg-white p-4" key={comment.id}>
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-sm font-semibold text-white">
                    {comment.author_init}
                  </span>
                  <div className="min-w-0 flex-1">
                    <strong className="flex flex-wrap items-center gap-2 text-sm font-semibold text-slate-950">
                      {comment.author}
                      <i className="text-xs font-medium not-italic text-slate-500">{comment.ago}</i>
                    </strong>
                    <p className="mt-1 text-sm leading-6 text-slate-600">{comment.body}</p>
                  </div>
                  {canModerate(comment.author_id) ? (
                    <Button aria-label="Delete comment" onClick={() => onDelete(comment.id)} size="icon" type="button" variant="ghost">
                      <Trash2 size={15} />
                    </Button>
                  ) : null}
                </article>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="rounded-lg border-slate-200/80 bg-white/90 shadow-sm">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 font-display text-xl tracking-normal text-slate-950">
            <UserRound size={18} />
            Related games
          </CardTitle>
        </CardHeader>
        <CardContent>
          {related.length === 0 ? (
            <p className="rounded-lg border border-dashed border-slate-200 bg-slate-50 p-6 text-center text-sm text-slate-500">
              Nothing related yet.
            </p>
          ) : (
            <div className="grid gap-3">
              {related.slice(0, 5).map((game) => (
                <button
                  className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white p-3 text-left transition hover:border-indigo-200 hover:bg-indigo-50/40"
                  key={game.id}
                  onClick={() => onOpen(game.id)}
                  type="button"
                >
                  <span className="h-14 w-20 shrink-0 rounded-md bg-slate-900 bg-cover bg-center" style={coverBackgroundStyle(game.cover)} />
                  <div className="min-w-0">
                    <strong className="line-clamp-1 text-sm font-semibold text-slate-950">{game.title}</strong>
                    <i className="text-xs not-italic text-slate-500">{game.plays_str} plays</i>
                  </div>
                </button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </section>
  );
}

export function DetailStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
      <strong className="block font-display text-xl font-semibold tracking-normal text-slate-950">{value}</strong>
      <span className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">{label}</span>
    </div>
  );
}
