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

const PHONE_SCANNER_IDS = ["phone", "numverify", "twilio", "abstract_phone"] as const;

const SECTIONS: { id: string; title: string; kinds: Finding["kind"][]; scanners?: string[] }[] = [
  { id: "identity", title: "Identity summary", kinds: [] },
  { id: "emails", title: "Emails", kinds: ["email"] },
  {
    id: "phone",
    title: "Phone",
    kinds: ["phone", "metadata", "note"],
    scanners: [...PHONE_SCANNER_IDS],
  },
  { id: "social", title: "Social profiles", kinds: ["profile"] },
  { id: "images", title: "Images", kinds: ["image"] },
  { id: "usernames", title: "Username candidates", kinds: ["username"] },
  { id: "dorks", title: "Search links / dorks", kinds: ["link"] },
  { id: "notes", title: "Notes", kinds: ["note", "breach"] },
];

const PHONE_SECTION_BLURB =
  "Free scanners give carrier, region, line type, and site registration. A subscriber name needs a CNAM API key (Twilio Lookup) or the manual reverse-lookup links in Search links. Empty CNAM is left empty.";

/** Homepage of a registrable domain (https://instagram.com/) is not a profile. */
export function isConcreteProfileUrl(url?: string | null): boolean {
  if (!url) return false;
  try {
    const parsed = new URL(url.includes("://") ? url : `https://${url}`);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return false;
    const parts = parsed.pathname.split("/").filter(Boolean);
    if (parts.length === 0) return false;
    const home = new Set(["home", "index", "index.html", "index.htm", "login", "signup", "register", "about", "www"]);
    if (parts.length === 1 && home.has(parts[0].toLowerCase())) return false;
    return true;
  } catch {
    return false;
  }
}

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
  const profileFindings = useMemo(
    () => allFindings.filter((f) => f.kind === "profile" && isConcreteProfileUrl(f.url)),
    [allFindings],
  );
  const phoneMeta = useMemo(
    () => derivePhoneMeta(findings, report?.identity),
    [findings, report],
  );
  const running = modules.some((m) => m.status === "running" || m.status === "queued");
  const done = modules.filter((m) => !["queued", "running"].includes(m.status)).length;
  const pct = modules.length ? Math.round((done / modules.length) * 100) : 0;

  if (error) {
    return (
      <div className="error-banner">
        {error}. <Link to="/">Start a new lookup</Link>
      </div>
    );
  }

  if (!report) {
    return <p className="hint">bootstrapping scan pipe…</p>;
  }

  return (
    <div>
      <div className="report-head">
        <div>
          <p className="kicker">{running ? "Live uplink" : "Packet complete"}</p>
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

      <div className={`scan-banner${running ? "" : " done"}`}>
        <span className="scan-label">{running ? "SCANNING" : "COMPLETE"}</span>
        {running && <span className="caret" aria-hidden />}
        <div className="scan-bar" aria-hidden>
          <i style={{ width: `${pct}%` }} />
        </div>
        <span className="meta">
          {done}/{modules.length || 0} modules · {pct}%
        </span>
      </div>

      <div className="identity">
        <div className="stat">
          <b>{uniq(allFindings, "email").length || (report.query.email ? 1 : 0)}</b>
          <span>Emails</span>
        </div>
        <div className="stat">
          <b>{profileFindings.length}</b>
          <span>Profiles</span>
        </div>
        <div className="stat">
          <b>{uniq(allFindings, "image").length}</b>
          <span>Images</span>
        </div>
        <div className="stat">
          <b>
            {modules.filter((m) => m.status === "success" || m.status === "empty").length}/
            {modules.length}
          </b>
          <span>Modules done</span>
        </div>
      </div>

      {(phoneMeta.callerName || phoneMeta.carrier || phoneMeta.region || phoneMeta.lineType) && (
        <div className="identity phone-meta">
          {phoneMeta.callerName && (
            <div className="stat">
              <b>{phoneMeta.callerName}</b>
              <span>Caller name (CNAM)</span>
            </div>
          )}
          {phoneMeta.carrier && (
            <div className="stat">
              <b>{phoneMeta.carrier}</b>
              <span>Carrier</span>
            </div>
          )}
          {phoneMeta.region && (
            <div className="stat">
              <b>{phoneMeta.region}</b>
              <span>Region</span>
            </div>
          )}
          {phoneMeta.lineType && (
            <div className="stat">
              <b>{phoneMeta.lineType}</b>
              <span>Line type</span>
            </div>
          )}
        </div>
      )}

      <div className="layout">
        <aside className="mod-list">
          <h3>Module ticks</h3>
          {modules.map((mod) => (
            <div className="mod" key={mod.id}>
              <div className="mod-left">
                <span className={`led ${mod.status}`} aria-hidden />
                <div>
                  <div className="name">{mod.name}</div>
                  <div className="hint">{mod.summary || (mod.status === "running" ? "probing…" : "queued")}</div>
                </div>
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
              if (section.id === "social") {
                return f.kind === "profile" && isConcreteProfileUrl(f.url);
              }
              if (section.scanners) {
                const from = section.scanners.flatMap((id) => findings[id] || []);
                return from.some((x) => x === f) && section.kinds.includes(f.kind);
              }
              if (section.id === "notes") {
                if (!section.kinds.includes(f.kind)) return false;
                return !PHONE_SCANNER_IDS.some((id) => (findings[id] || []).includes(f));
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
                {section.id === "phone" && (
                  <p className="section-blurb">{PHONE_SECTION_BLURB}</p>
                )}
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
                          {findingHref(f) ? (
                            <a href={findingHref(f)!} target="_blank" rel="noreferrer">
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

function findingHref(f: Finding): string | null {
  if (!f.url) return null;
  if (f.kind === "profile" && !isConcreteProfileUrl(f.url)) return null;
  return f.url;
}

function derivePhoneMeta(
  findings: Record<string, Finding[]>,
  identity?: Report["identity"],
) {
  let carrier = identity?.phone_carrier || "";
  let region = identity?.phone_region || "";
  let lineType = identity?.phone_line_type || "";
  let callerName = identity?.caller_name || "";
  for (const id of PHONE_SCANNER_IDS) {
    for (const f of findings[id] || []) {
      const title = (f.title || "").trim().toLowerCase();
      const extra = f.extra || {};
      if (!carrier && (title === "carrier" || title === "carrier (dataset)") && f.value) {
        carrier = f.value;
      }
      if (!region && (title === "region" || title === "location") && f.value) {
        region = f.value;
      }
      if (!lineType && title === "line type" && f.value) {
        lineType = f.value;
      }
      if (!callerName && f.kind === "metadata" && (title === "caller name (cnam)" || title === "caller name")) {
        callerName = f.value;
      }
      if (!carrier && typeof extra.carrier === "string") carrier = extra.carrier;
      if (!region && typeof extra.region === "string") region = extra.region;
      if (!lineType && typeof extra.line_type === "string") lineType = extra.line_type;
    }
  }
  return { carrier, region, lineType, callerName };
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
