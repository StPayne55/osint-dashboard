export type QueryType = "auto" | "email" | "phone" | "username" | "name";

export type Finding = {
  kind:
    | "email"
    | "phone"
    | "profile"
    | "image"
    | "link"
    | "note"
    | "metadata"
    | "username"
    | "breach";
  title: string;
  value: string;
  url?: string | null;
  extra?: Record<string, unknown>;
};

export type ModuleStatus = {
  id: string;
  name: string;
  status:
    | "queued"
    | "running"
    | "success"
    | "empty"
    | "error"
    | "timeout"
    | "skipped"
    | "unavailable";
  summary: string;
  error?: string | null;
  duration_ms: number;
  finding_count: number;
};

export type Query = {
  raw: string;
  type: QueryType;
  email?: string | null;
  phone_e164?: string | null;
  username?: string | null;
  name?: string | null;
  domain?: string | null;
  username_candidates: string[];
};

export type ScannerInfo = {
  id: string;
  name: string;
  tool: string;
  description: string;
  accepts: QueryType[];
  optional_key?: string | null;
  limitations: string;
  available: boolean;
};

export type Report = {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed";
  created_at: number;
  finished_at?: number | null;
  query: Query;
  identity?: {
    emails: string[];
    phones: string[];
    usernames: string[];
    profiles: number;
    images: number;
    notes: string[];
  } | null;
  modules: ModuleStatus[];
  findings: Record<string, Finding[]>;
  honesty: string;
};

export type ScanEvent =
  | {
      type: "job";
      status: "started" | "completed" | "failed";
      job_id: string;
      query?: Query;
      scanners?: ScannerInfo[];
      report?: Report;
    }
  | {
      type: "scanner";
      id: string;
      name?: string;
      status: ModuleStatus["status"] | "running";
      result?: {
        scanner_id: string;
        name: string;
        status: ModuleStatus;
        findings: Finding[];
        raw?: unknown;
      };
    };

const prefix = "";

export async function detectQuery(q: string, type: QueryType = "auto") {
  const url = `${prefix}/api/detect?q=${encodeURIComponent(q)}&type=${type}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<{ guessed: QueryType; query: Query }>;
}

export async function fetchCatalog() {
  const res = await fetch(`${prefix}/api/catalog`);
  if (!res.ok) throw new Error("Catalog unavailable");
  return res.json() as Promise<{
    app: string;
    honesty: string;
    scanners: ScannerInfo[];
  }>;
}

export async function startScan(query: string, type: QueryType) {
  const res = await fetch(`${prefix}/api/scans`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, type }),
  });
  if (res.status === 429) {
    throw new Error("Rate limited — wait a few minutes before the next scan.");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || "Scan failed to start");
  }
  return res.json() as Promise<{ job_id: string; query: Query; scanners: string[] }>;
}

export async function fetchReport(jobId: string) {
  const res = await fetch(`${prefix}/api/scans/${jobId}`);
  if (!res.ok) throw new Error("Scan not found");
  return res.json() as Promise<Report>;
}

export function eventsUrl(jobId: string) {
  return `${prefix}/api/scans/${jobId}/events`;
}

export function exportUrl(jobId: string) {
  return `${prefix}/api/scans/${jobId}/export.json`;
}
