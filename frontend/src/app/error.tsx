"use client";

export default function ErrorBoundary({ reset }: { reset: () => void }) {
  return (
    <section className="card auth-gate" role="alert">
      <h1>This view could not load</h1>
      <p>Your saved work remains on the server. Try loading the view again.</p>
      <button className="primary" onClick={reset}>Try again</button>
    </section>
  );
}
