import { MessageCircle, Trash2, UserRound } from "lucide-react";
import type { ReactNode } from "react";

import { coverBackgroundStyle } from "@/lib/cover";
import type { Comment, Game } from "@/lib/types";

export function Centered({ children }: { children: ReactNode }) {
  return <div className="pf-state-page">{children}</div>;
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
                <span style={coverBackgroundStyle(game.cover)} />
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

export function DetailStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}
