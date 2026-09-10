"use client";

export default function ErrorPage({ reset }: { reset: () => void }) {
  return <main className="auth-shell"><section className="auth-card"><h1>Unable to open your workspace</h1><p>The server may be offline. Your information has not been replaced with demo data.</p><button className="button primary" onClick={reset}>Try again</button><a className="auth-back" href="/login">Return to sign in</a></section></main>;
}
