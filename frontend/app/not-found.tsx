import Link from "next/link";

export default function NotFound() {
  return (
    <main className="pf-status-page">
      <section className="pf-status-card">
        <span className="pf-status-code">Error 404</span>
        <h1>Page not found</h1>
        <p>The page you are looking for does not exist or may have been moved.</p>
        <div className="pf-status-actions">
          <Link href="/">Back to arcade</Link>
        </div>
      </section>
    </main>
  );
}
