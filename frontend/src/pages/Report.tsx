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
import { SocialBadges } from "../components/SocialBadges";
import { collectPhotoFindings, isImageDork, type PhotoItem } from "../lib/photos";
import {
  curatePhoneCardFindings,
  formatPhoneNumber,
  hasResolvedPhone,
  PHONE_SCANNER_IDS,
  pickBestCarrier,
  pickBestLineType,
  pickHeroName,
  resolvePhoneFormatInput,
} from "../lib/phoneDisplay";
import { groupEnumeratedFindings } from "../lib/enumeratedFields";
import {
  collectConfirmedSocials,
  isConcreteProfileUrl,
  isConfirmedSocialFinding,
} from "../lib/socials";
import {
  addressDisplayFields,
  groupTrestlePhoneFindings,
  isTrestleCurrentAddress,
  ownerDisplayFields,
  ownersForDisplay,
  partitionOwnersByPrimary,
  takeCompetingCallerName,
  type TrestleOwnerGroup,
} from "../lib/trestle";

export { isConcreteProfileUrl } from "../lib/socials";

const SECTIONS: { id: string; title: string; kinds: Finding["kind"][]; scanners?: string[] }[] = [
  { id: "identity", title: "Identity summary", kinds: [] },
  { id: "images", title: "Photos / Avatars", kinds: ["image"] },
  { id: "emails", title: "Emails", kinds: ["email"] },
  {
    id: "phone",
    title: "Phone",
    kinds: ["phone", "metadata", "note"],
    scanners: [...PHONE_SCANNER_IDS],
  },
  { id: "social", title: "Socials", kinds: ["profile", "note"] },
  { id: "usernames", title: "Username candidates", kinds: ["username"] },
  { id: "dorks", title: "Search links / dorks", kinds: ["link"] },
  { id: "notes", title: "Notes", kinds: ["note", "breach"] },
];

const DORKS_SECTION_BLURB =
  "LinkedIn rows sit at the top for name, email, and username lookups. They open a Google profile dork or LinkedIn people search in your browser (login may be required). This desk never scrapes LinkedIn.";

const PHOTOS_SECTION_BLURB =
  "Public avatars only: Gravatar when the owner published one, plus display photos Maigret parsed from claimed profiles. Extra image/photo/avatar URLs on a finding are collected when they are concrete http(s) links. No LinkedIn, Google Images, or face-search scraping.";

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
  const confirmedSocials = useMemo(() => collectConfirmedSocials(allFindings), [allFindings]);
  const leftoverNotes = useMemo(
    () =>
      dedupe(
        allFindings.filter((f) => {
          if (f.kind !== "note" && f.kind !== "breach") return false;
          if (PHONE_SCANNER_IDS.some((id) => (findings[id] || []).includes(f))) return false;
          return !isConfirmedSocialFinding(f);
        }),
      ),
    [allFindings, findings],
  );
  const photoItems = useMemo(() => collectPhotoFindings(allFindings), [allFindings]);
  const imageDorks = useMemo(() => allFindings.filter(isImageDork), [allFindings]);
  const phoneMeta = useMemo(
    () => derivePhoneMeta(findings, report?.identity),
    [findings, report],
  );
  const showPhoneSection = useMemo(
    () => hasResolvedPhone(report?.query, report?.identity, findings),
    [report, findings],
  );
  const formattedPhone = useMemo(
    () => formatPhoneNumber(resolvePhoneFormatInput(report?.query, report?.identity, findings)),
    [report, findings],
  );
  const displayedTrestleOwners = useMemo(() => {
    const phoneFindings = PHONE_SCANNER_IDS.flatMap((id) => findings[id] || []);
    return ownersForDisplay(groupTrestlePhoneFindings(phoneFindings).owners);
  }, [findings]);
  const heroName = useMemo(
    () =>
      pickHeroName(
        phoneMeta.callerName,
        phoneMeta.whitepagesOwner,
        ...displayedTrestleOwners.map((owner) => owner.name),
      ),
    [phoneMeta, displayedTrestleOwners],
  );
  const emailCount = uniq(allFindings, "email").length || (report?.query.email ? 1 : 0);
  const modulesDone = modules.filter((m) => m.status === "success" || m.status === "empty").length;
  const sectionOrder = useMemo(() => {
    const rest = SECTIONS.filter((s) => {
      if (s.id === "identity" || s.id === "phone") return false;
      if (s.id === "social") return confirmedSocials.length > 0;
      if (s.id === "notes") return leftoverNotes.length > 0;
      return true;
    });
    const phone = SECTIONS.find((s) => s.id === "phone");
    if (showPhoneSection && phone) return [phone, ...rest];
    return rest;
  }, [showPhoneSection, confirmedSocials.length, leftoverNotes.length]);
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
          <p className="kicker">{running ? "Searching…" : "Ready"}</p>
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

      <div className="identity-card">
        {heroName ? <div className="identity-name">{heroName}</div> : null}
        <div className="identity-counts">
          <span>
            <b>{emailCount}</b> Emails
          </span>
          <span>
            <b>{confirmedSocials.length}</b> Socials
          </span>
          <span>
            <b>{photoItems.length}</b> Photos
          </span>
        </div>
        {(phoneMeta.carrier || phoneMeta.lineType) && (
          <p className="identity-phone-meta">
            {[phoneMeta.carrier, phoneMeta.lineType].filter(Boolean).join(" · ")}
          </p>
        )}
      </div>

      {photoItems.length > 0 && (
        <div className="photo-strip" aria-label="Photos and avatars">
          {photoItems.slice(0, 4).map((photo, i) => (
            <PhotoCard key={`${photo.url}-${i}`} photo={photo} compact />
          ))}
        </div>
      )}

      <div className="layout">
        <aside className="mod-list">
          <h3>
            Module ticks{" "}
            <span className="meta">
              {modulesDone}/{modules.length}
            </span>
          </h3>
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
          {sectionOrder.map((section) => {
            const rows = allFindings.filter((f) => {
              if (section.scanners) {
                const from = section.scanners.flatMap((id) => findings[id] || []);
                return from.some((x) => x === f) && section.kinds.includes(f.kind);
              }
              if (section.id === "notes") {
                return leftoverNotes.includes(f);
              }
              return section.kinds.includes(f.kind);
            });
            const unique = section.id === "dorks" ? pinLinkedInFirst(dedupe(rows)) : dedupe(rows);
            return (
              <section className="section" key={section.id} id={section.id}>
                <h3>
                  {section.title}{" "}
                  <span className="meta">
                    {section.id === "images"
                      ? photoItems.length
                      : section.id === "phone"
                        ? phoneSectionCount(unique, formattedPhone, heroName)
                        : section.id === "social"
                          ? confirmedSocials.length
                          : unique.length}
                  </span>
                </h3>
                {section.id === "dorks" && (
                  <p className="section-blurb">{DORKS_SECTION_BLURB}</p>
                )}
                {section.id === "images" && (
                  <p className="section-blurb">{PHOTOS_SECTION_BLURB}</p>
                )}
                {section.id === "images" ? (
                  <>
                    {photoItems.length ? (
                      <div className="images photo-gallery">
                        {photoItems.map((photo, i) => (
                          <PhotoCard key={`${photo.url}-${i}`} photo={photo} />
                        ))}
                      </div>
                    ) : (
                      <p className="empty">
                        {running ? "Still collecting…" : "No public profile photo found."}
                      </p>
                    )}
                    {imageDorks.length > 0 && (
                      <div className="photo-dorks">
                        {imageDorks.map((f, i) => (
                          <a
                            key={`${f.title}-${i}`}
                            className="photo-dork"
                            href={findingHref(f) || undefined}
                            target="_blank"
                            rel="noreferrer noopener"
                          >
                            {f.title}
                          </a>
                        ))}
                      </div>
                    )}
                  </>
                ) : section.id === "social" ? (
                  <SocialBadges items={confirmedSocials} />
                ) : section.id === "phone" ? (
                  <PhoneOrFindingList
                    items={unique}
                    sectionId={section.id}
                    formattedPhone={formattedPhone}
                    primaryName={heroName}
                  />
                ) : unique.length ? (
                  <PhoneOrFindingList items={unique} sectionId={section.id} />
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

function PhoneOrFindingList({
  items,
  sectionId,
  formattedPhone = "",
  primaryName = "",
}: {
  items: Finding[];
  sectionId: string;
  formattedPhone?: string;
  primaryName?: string;
}) {
  if (sectionId !== "phone") {
    return <FindingList items={items} sectionId={sectionId} />;
  }
  const { owners, leftover } = groupTrestlePhoneFindings(items);
  const { primary, competing } = partitionOwnersByPrimary(owners, primaryName);
  const resolvedNames = [primaryName, ...primary.map((owner) => owner.name), ...competing.map((owner) => owner.name)];
  const { rows: phoneRows, competingCnam } = takeCompetingCallerName(
    curatePhoneCardFindings(leftover, formattedPhone, resolvedNames),
    primaryName,
  );
  if (!phoneRows.length && !primary.length && !competing.length && !competingCnam) {
    return <p className="empty">No public hits in this section.</p>;
  }
  return (
    <div className="findings">
      {phoneRows.map((f, i) => (
        <FindingRow key={`${f.title}-${f.value}-${i}`} finding={f} sectionId={sectionId} />
      ))}
      {primary.map((owner) => (
        <TrestleOwnerCard key={`trestle-owner-${owner.ownerIndex}`} owner={owner} />
      ))}
      <OtherPotentialMatches owners={competing} cnam={competingCnam} />
    </div>
  );
}

function OtherPotentialMatches({
  owners,
  cnam,
}: {
  owners: TrestleOwnerGroup[];
  cnam: Finding | null;
}) {
  if (!owners.length && !cnam) return null;
  return (
    <details className="other-matches">
      <summary>other potential matches</summary>
      <div className="other-matches-body">
        {cnam ? <FindingRow finding={cnam} sectionId="phone" /> : null}
        {owners.map((owner) => (
          <TrestleOwnerCard key={`trestle-other-${owner.ownerIndex}`} owner={owner} />
        ))}
      </div>
    </details>
  );
}

function phoneSectionCount(items: Finding[], formattedPhone: string, primaryName = ""): number {
  const { owners, leftover } = groupTrestlePhoneFindings(items);
  const { primary, competing } = partitionOwnersByPrimary(owners, primaryName);
  const resolvedNames = [primaryName, ...primary.map((owner) => owner.name), ...competing.map((owner) => owner.name)];
  const { rows, competingCnam } = takeCompetingCallerName(
    curatePhoneCardFindings(leftover, formattedPhone, resolvedNames),
    primaryName,
  );
  return rows.length + primary.length + competing.length + (competingCnam ? 1 : 0);
}

function FindingList({ items, sectionId }: { items: Finding[]; sectionId: string }) {
  if (sectionId === "usernames") {
    return (
      <div className="findings enumerated-values" aria-label="Username candidates">
        {items.map((finding, i) => (
          <ValueRow key={`${finding.title}-${finding.value}-${i}`} finding={finding} className="enumerated-value" />
        ))}
      </div>
    );
  }
  return (
    <div className="findings">
      {groupEnumeratedFindings(items).map((group, i) => {
        if (group.type === "enumerated") {
          return (
            <div className="enumerated-group" key={`${group.label}-${i}`}>
              <div className="title">{group.label}</div>
              <div className="enumerated-values">
                {group.findings.map((finding, j) => (
                  <ValueRow key={`${finding.title}-${finding.value}-${j}`} finding={finding} className="enumerated-value" />
                ))}
              </div>
            </div>
          );
        }
        return (
          <FindingRow
            key={`${group.finding.title}-${group.finding.value}-${i}`}
            finding={group.finding}
            sectionId={sectionId}
          />
        );
      })}
    </div>
  );
}

function FindingRow({ finding, sectionId }: { finding: Finding; sectionId: string }) {
  return (
    <div className={findingClassName(finding, sectionId)}>
      <div className="title">
        {finding.title}
        {finding.extra?.source === "pdl" ? <span className="meta"> · PDL</span> : null}
        {finding.extra?.source === "whitepages" ? <span className="meta"> · Whitepages</span> : null}
      </div>
      <ValueRow finding={finding} />
    </div>
  );
}

function ValueRow({ finding, className }: { finding: Finding; className?: string }) {
  const href = findingHref(finding);
  const text = finding.value || finding.url;
  return (
    <div className={className ? `${className} value` : "value"}>
      {href ? (
        <a href={href} target="_blank" rel="noreferrer">
          {text}
        </a>
      ) : (
        text
      )}
    </div>
  );
}

function TrestleOwnerCard({ owner }: { owner: TrestleOwnerGroup }) {
  const chips = ownerDisplayFields(owner.ownerFields);
  const heading = owner.name || "Owner";
  return (
    <div className="trestle-owner">
      <div className="trestle-owner-head">
        <div className="title">Name</div>
        <div className="value trestle-owner-name">{heading}</div>
      </div>
      {chips.length > 0 && (
        <div className="trestle-chips">
          {chips.map((chip) => (
            <span className="trestle-chip" key={chip.key}>
              <span className="trestle-chip-label">{chip.label}</span>
              <b>{chip.value}</b>
            </span>
          ))}
        </div>
      )}
      {owner.alternateNames.length > 0 && (
        <div className="trestle-alts">
          <div className="title">Aliases</div>
          <div className="enumerated-values">
            {owner.alternateNames.map((alt) => (
              <div className="value" key={alt}>
                {alt}
              </div>
            ))}
          </div>
        </div>
      )}
      {owner.addresses.length > 0 && (
        <div className="trestle-addresses">
          {owner.addresses.map((finding, i) => (
            <TrestleAddressRow
              key={`${finding.value}-${i}`}
              finding={finding}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function TrestleAddressRow({ finding }: { finding: Finding }) {
  const current = isTrestleCurrentAddress(finding);
  const extra = finding.extra && typeof finding.extra === "object" ? finding.extra : {};
  const fields =
    extra.fields && typeof extra.fields === "object" && !Array.isArray(extra.fields)
      ? (extra.fields as Record<string, unknown>)
      : {};
  const rows = addressDisplayFields(fields);
  return (
    <details className={`trestle-address${current ? " current" : ""}`}>
      <summary>
        {current ? <span className="current-badge">Current Address</span> : <span className="address-kind">Address</span>}
        <span className="address-line">{finding.value}</span>
      </summary>
      {rows.length ? (
        <dl className="trestle-fields">
          {rows.map((row) => (
            <div key={row.key}>
              <dt>{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="empty trestle-empty">No additional address fields returned.</p>
      )}
    </details>
  );
}

function PhotoCard({ photo, compact = false }: { photo: PhotoItem; compact?: boolean }) {
  const [broken, setBroken] = useState(false);
  return (
    <figure className={`photo-card${compact ? " compact" : ""}${broken ? " broken" : ""}`}>
      <a href={photo.url} target="_blank" rel="noreferrer noopener">
        {broken ? (
          <div className="photo-fallback" role="img" aria-label={`${photo.title} failed to load`}>
            broken image
          </div>
        ) : (
          <img
            src={photo.url}
            alt={photo.title}
            referrerPolicy="no-referrer"
            onError={() => setBroken(true)}
          />
        )}
      </a>
      <figcaption>
        <span className="photo-title">{photo.title}</span>
        {photo.source ? <span className="photo-source">{photo.source}</span> : null}
      </figcaption>
    </figure>
  );
}

function isLinkedInFinding(f: Finding): boolean {
  return (f.title || "").toLowerCase().startsWith("linkedin");
}

function pinLinkedInFirst(items: Finding[]): Finding[] {
  return [...items].sort((a, b) => Number(isLinkedInFinding(b)) - Number(isLinkedInFinding(a)));
}

function findingClassName(f: Finding, sectionId: string): string {
  return isLinkedInFinding(f) && sectionId === "dorks" ? "finding linkedin" : "finding";
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
  const phoneFindings = PHONE_SCANNER_IDS.flatMap((id) => findings[id] || []);
  let carrier = pickBestCarrier(phoneFindings)?.value || identity?.phone_carrier || "";
  let region = identity?.phone_region || "";
  let lineType = pickBestLineType(phoneFindings)?.value || identity?.phone_line_type || "";
  let callerName = identity?.caller_name || "";
  let whitepagesOwner = "";
  let trestleOwner = "";
  for (const f of phoneFindings) {
    const title = (f.title || "").trim().toLowerCase();
    const extra = f.extra || {};
    if (!region && (title === "region" || title === "location") && f.value) {
      region = f.value;
    }
    if (!callerName && f.kind === "metadata" && (title === "caller name (cnam)" || title === "caller name")) {
      callerName = f.value;
    }
    if (!whitepagesOwner && extra.source === "whitepages" && title === "name" && f.value) {
      whitepagesOwner = f.value;
    }
    if (!trestleOwner && extra.source === "trestle" && title === "name" && f.value) {
      trestleOwner = f.value;
    }
    if (!carrier && typeof extra.carrier === "string") carrier = extra.carrier;
    if (!region && typeof extra.region === "string") region = extra.region;
    if (!lineType && typeof extra.line_type === "string") lineType = extra.line_type;
  }
  return { carrier, region, lineType, callerName, whitepagesOwner, trestleOwner };
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
