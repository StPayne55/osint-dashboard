import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  eventsUrl,
  exportUrl,
  fetchReport,
  type Finding,
  type ModuleStatus,
  type Report,
  type ScanEvent,
} from "../lib/api";

const SECTIONS: { id: string; title: string; kinds: Finding["kind"][]; scanners?: string[] }[] = [
  { id: "identity", title: "Identity summary", kinds: [] },
  { id: "emails", title: "Emails", kinds: ["email"] },
  { id: "phone", title: "Phone", kinds: ["phone", "metadata"], scanners: ["phone", "numverify"] },
  { id: "social", title: "Social profiles", kinds: ["profile"] },
  { id: "images", title: "Images", kinds: ["image"] },
  { id: "usernames", title: "Username candidates", kinds: ["username"] },
  { id: "dorks", title: "Search links / dorks", kinds: ["link"] },
  { id: "notes", title: "Notes", kinds: ["note", "breach"] },
];

export function ReportPage() {
  const { jobId } = useParams();
  const [report, setReport] = useState<Report | null>(null);
  const [modules, setModules] = useState<ModuleStatus[]>([]);
  const [findings, setFindings] = useState<Record<string, Finding[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [rawOpen, setRawOpen] = useState(false);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    fetchReport(jobId)
      .then((r) => {
        if (cancelled) return;
        setReport(r);
        setModules(r.modules);
        setFindings(r.findings);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Load failed");
      });

    const source = new EventSource(eventsUrl(jobId));
    source.onmessage = (msg) => {
      const event = JSON.parse(msg.data) as ScanEvent;
      if (event.type === "job" && event.status === "started") {
        setModules(
          (event.scanners || []).map((s) => ({
            id: s.id,
            name: s.name,
            status: "queued",
            summary: "",
            duration_ms: 0,
            finding_count: 0,
          })),
        );
      }
      if (event.type === "scanner") {
        setModules((prev) => {
          const next = prev.map((m) =>
            m.id === event.id
              ? event.result?.status || {
                  ...m,
                  status: event.status,
                  name: event.name || m.name,
                }
              : m,
          );
          if (!next.some((m) => m.id === event.id)) {
            next.push(
              event.result?.status || {
                id: event.id,
                name: event.name || event.id,
                status: event.status,
                summary: "",
                duration_ms: 0,
                finding_count: 0,
              },
            );
          }
          return next;
        });
        if (event.result) {
          setFindings((prev) => ({ ...prev, [event.id]: event.result!.findings }));
        }
      }
      if (event.type === "job" && event.status === "completed" && event.report) {
        setReport(event.report);
        setModules(event.report.modules);
        setFindings(event.report.findings);
        source.close();
      }
    };
    source.onerror = () => {
      // EventSource retries; if the job already finished this is harmless.
    };
    return () => {
      cancelled = true;
      source.close();
    };
  }, [jobId]);

  const allFindings = useMemo(() => Object.values(findings).flat(), [findings]);
  const running = modules.some((m) => m.status === "running" || m.status === "queued");

  if (error) {
    return (
      <div className="error-banner">
        {error}. <Link to="/">Start a new lookup</Link>
      </div>
    );
  }

  if (!report) {
    return <p className="hint">Opening scan…</p>;
  }

  return (
    <div>
      <div className="report-head">
        <div>
          <p className="kicker">{running ? "Live collection" : "Report"}</p>
          <h2>{report.query.raw}</h2>
          <p className="meta">
            type {report.query.type}
            {report.query.email ? ` · ${report.query.email}` : ""}
            {report.query.phone_e164 ? ` · ${report.query.phone_e164}` : ""}
            {jobId ? ` · job ${jobId}` : ""}
          </p>
        </div>
        <div className="demo-row">
          <Link className="btn ghost" to="/">
            New lookup
          </Link>
          {jobId && (
            <a className="btn" href={exportUrl(jobId)}>
              Export JSON
            </a>
          )}
        </div>
      </div>

      <div className="identity">
        <div className="stat">
          <b>{uniq(allFindings, "email").length || (report.query.email ? 1 : 0)}</b>
          <span>Emails</span>
        </div>
        <div className="stat">
          <b>{uniq(allFindings, "profile").length}</b>
          <span>Profiles</span>
        </div>
        <div className="stat">
          <b>{uniq(allFindings, "image").length}</b>
          <span>Images</span>
        </div>
        <div className="stat">
          <b>{modules.filter((m) => m.status === "success" || m.status === "empty").length}/{modules.length}</b>
          <span>Modules done</span>
        </div>
      </div>

      <div className="layout">
        <aside className="mod-list">
          <h3>Module status</h3>
          {modules.map((mod) => (
            <div className="mod" key={mod.id}>
              <div>
                <div className="name">{mod.name}</div>
                <div className="hint">{mod.summary || "Waiting"}</div>
              </div>
              <div className={`status ${mod.status}`}>{mod.status}</div>
            </div>
          ))}
        </aside>

        <div>
          <section className="section honesty">
            <h3>Honesty</h3>
            <p>{report.honesty}</p>
          </section>

          {SECTIONS.filter((s) => s.id !== "identity").map((section) => {
            const rows = allFindings.filter((f) => {
              if (section.scanners) {
                const from = section.scanners.flatMap((id) => findings[id] || []);
                return from.some((x) => x === f) && section.kinds.includes(f.kind);
              }
              return section.kinds.includes(f.kind);
            });
            const unique = dedupe(rows);
            return (
              <section className="section" key={section.id} id={section.id}>
                <h3>
                  {section.title}{" "}
                  <span className="meta">{unique.length}</span>
                </h3>
                {section.id === "images" ? (
                  unique.length ? (
                    <div className="images">
                      {unique.map((f, i) => (
                        <a key={i} href={f.url || f.value} target="_blank" rel="noreferrer">
                          <img src={f.url || f.value} alt={f.title} />
                        </a>
                      ))}
                    </div>
                  ) : (
                    <p className="empty">No public profile image found.</p>
                  )
                ) : unique.length ? (
                  <div className="findings">
                    {unique.map((f, i) => (
                      <div className="finding" key={`${f.title}-${f.value}-${i}`}>
                        <div className="title">{f.title}</div>
                        <div className="value">
                          {f.url ? (
                            <a href={f.url} target="_blank" rel="noreferrer">
                              {f.value || f.url}
                            </a>
                          ) : (
                            f.value
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="empty">
                    {running ? "Still collecting…" : "No public hits in this section."}
                  </p>
                )}
              </section>
            );
          })}

          <section className="section">
            <h3>Raw JSON</h3>
            <button className="btn ghost" type="button" onClick={() => setRawOpen((v) => !v)}>
              {rawOpen ? "Hide" : "Show"} assembled report
            </button>
            {rawOpen && (
              <pre className="json-block">{JSON.stringify({ report, findings, modules }, null, 2)}</pre>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function uniq(items: Finding[], kind: Finding["kind"]) {
  return dedupe(items.filter((i) => i.kind === kind));
}

function dedupe(items: Finding[]) {
  const seen = new Set<string>();
  return items.filter((item) => {
    const key = `${item.kind}|${item.title}|${item.value}|${item.url || ""}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
