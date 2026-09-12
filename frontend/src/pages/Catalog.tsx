import { useEffect, useState } from "react";
import { fetchCatalog, type ScannerInfo } from "../lib/api";

export function Catalog() {
  const [scanners, setScanners] = useState<ScannerInfo[]>([]);
  const [honesty, setHonesty] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchCatalog()
      .then((data) => {
        setScanners(data.scanners);
        setHonesty(data.honesty);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed"));
  }, []);

  return (
    <div>
      <section className="hero">
        <p className="kicker">Module catalog</p>
        <h2>Every scanner, what it accepts, and what it will not invent.</h2>
        <p className="lede">{honesty}</p>
      </section>
      {error && <div className="error-banner">{error}</div>}
      <div className="catalog">
        {scanners.map((scanner) => (
          <article key={scanner.id}>
            <h3>{scanner.name}</h3>
            <div className="tags">
              <span className="tag">{scanner.tool}</span>
              {scanner.accepts.map((a) => (
                <span className="tag" key={a}>
                  {a}
                </span>
              ))}
              <span className={scanner.available ? "tag ok" : "tag no"}>
                {scanner.available ? "ready" : "unavailable / disabled"}
              </span>
              {scanner.optional_key && <span className="tag">{scanner.optional_key}</span>}
            </div>
            <p>{scanner.description}</p>
            <p className="hint">{scanner.limitations}</p>
          </article>
        ))}
      </div>
    </div>
  );
}
