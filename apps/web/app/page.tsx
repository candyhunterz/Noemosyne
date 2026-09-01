export default function Home() {
  return (
    <>
      <p className="pill">Milestone 1</p>
      <h1>Beliefs with their reasons still attached.</h1>
      <p className="lede">
        Noemosyne keeps claims, attributed assertions, evidence judgments, disagreement,
        and belief revision distinct—so an answer can show what was known, why, and when.
      </p>
      <div className="grid">
        <section className="card"><h2>Trace provenance</h2><p>Every accepted judgment resolves to source locators and review history.</p></section>
        <section className="card"><h2>Keep disagreement</h2><p>Support, challenge, and context remain visible and dependency-grouped.</p></section>
        <section className="card"><h2>Read historically</h2><p>Knowledge cutoffs exclude information recorded later, preventing temporal leakage.</p></section>
      </div>
    </>
  );
}
