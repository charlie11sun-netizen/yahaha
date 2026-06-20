"use client";

import Link from "next/link";
import { useEffect } from "react";

export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="pf-status-page">
      <section className="pf-status-card">
        <span className="pf-status-code is-error">Something went wrong</span>
        <h1>Unexpected error</h1>
        <p>{error?.message || "An unexpected error occurred while rendering this page."}</p>
        <div className="pf-status-actions">
          <button onClick={() => reset()} type="button">Try again</button>
          <Link href="/">Back to home</Link>
        </div>
      </section>
    </main>
  );
}
