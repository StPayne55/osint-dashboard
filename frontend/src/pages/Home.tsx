import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { detectQuery, startScan, type QueryType } from "../lib/api";

const TYPES: { id: QueryType; label: string }[] = [
  { id: "auto", label: "Auto-detect" },
  { id: "email", label: "Email" },
  { id: "phone", label: "Phone" },
  { id: "username", label: "Username" },
  { id: "name", label: "Full name" },
];

const DEMOS = [
  { label: "example@example.com", query: "example@example.com", type: "email" as QueryType },
  { label: "torvalds", query: "torvalds", type: "username" as QueryType },
  { label: "+1 202 456 1111", query: "+1 202 456 1111", type: "phone" as QueryType },
  { label: "Ada Lovelace", query: "Ada Lovelace", type: "name" as QueryType },
];

export function Home() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [type, setType] = useState<QueryType>("auto");
  const [guess, setGuess] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (query.trim().length < 3) {
      setGuess("");
      return;
    }
    const handle = window.setTimeout(() => {
      detectQuery(query, type)
        .then((d) => {
          const t = d.query.type;
          const extra = d.query.email || d.query.phone_e164 || d.query.username || d.query.name;
          setGuess(`> classified as ${t}${extra ? ` · ${extra}` : ""}`);
        })
        .catch(() => setGuess(""));
    }, 280);
    return () => window.clearTimeout(handle);
  }, [query, type]);

  const canSubmit = useMemo(() => query.trim().length >= 2 && !busy, [query, busy]);

  async function onSubmit(event?: FormEvent) {
    event?.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      const started = await startScan(query.trim(), type);
      navigate(`/scan/${started.job_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start scan");
      setBusy(false);
    }
  }

  return (
    <div>
      <section className="hero">
        <p className="kicker">Self-hosted // public sources only</p>
        <h2>People lookup from open-source OSINT — not a secret dossier.</h2>
        <p className="lede">
          Enter a name, email, phone, or username. Modules such as Holehe, Sherlock,
          Maigret, SpiderFoot (open source), Gravatar, and phone metadata run in
          parallel and stream into a single report. Empty results stay empty.
          Nothing is written to disk by default.
        </p>
      </section>

      <form className="search-card glass" onSubmit={onSubmit}>
        <div className="term-chrome">
          <div className="term-dots" aria-hidden>
            <i />
            <i />
            <i />
          </div>
          <span>session://lookup</span>
        </div>
        <div className="search-row">
          <label className={`term-input${query ? " has-value" : ""}`}>
            <span className="term-prompt">root@desk:~$</span>
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="name, email, phone, or @username"
              aria-label="Search query"
            />
            <span className="caret" aria-hidden />
          </label>
          <button type="submit" disabled={!canSubmit}>
            {busy ? "Queuing…" : "Scan"}
          </button>
        </div>
        <div className="type-row">
          {TYPES.map((item) => (
            <button
              key={item.id}
              type="button"
              className={type === item.id ? "on" : ""}
              onClick={() => setType(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
        {guess && <p className="hint">{guess}</p>}
        {error && <div className="error-banner">{error}</div>}
        <div className="demo-row">
          {DEMOS.map((demo) => (
            <button
              key={demo.label}
              type="button"
              onClick={() => {
                setQuery(demo.query);
                setType(demo.type);
              }}
            >
              load {demo.label}
            </button>
          ))}
        </div>
      </form>
    </div>
  );
}
