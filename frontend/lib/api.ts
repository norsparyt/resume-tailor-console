export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

export type ChangeKind = "rephrase" | "reorder" | "emphasize" | "condense" | "remove";

export interface Change {
  id: string;
  section: string;
  kind: ChangeKind;
  original: string;
  proposed: string;
  rationale: string;
  keywords: string[];
  start: number;
  end: number;
  warnings: string[];
}

export interface RejectedChange {
  id: string;
  section: string;
  original: string;
  proposed: string;
  reason: string;
}

export interface Gap {
  requirement: string;
  importance: "critical" | "important" | "nice-to-have";
  reason: string;
  suggestion: string;
}

export interface Keywords {
  jd_keywords: string[];
  already_present: string[];
  surfaced_by_changes: string[];
  missing: string[];
}

export interface TailorResult {
  company: string; // hiring company from Claude's reply, used for the PDF file name
  summary: string;
  changes: Change[];
  rejected: RejectedChange[];
  unfillable_gaps: Gap[];
  keywords: Keywords;
  pages_if_all_accepted: number | null;
  notes: string[];
  base_resume: string;
}

export interface CompileResult {
  id: string;
  pages: number;
  one_page: boolean;
  errors: string[];
  pdf_url: string;
  tex_url: string;
  tex: string;
}

// Where text clicked on a compiled PDF comes from in that compile's LaTeX: the line (from 1)
// and, when the clicked word was found in it, the characters it spans.
export interface SourceSpot {
  line: number;
  start: number | null;
  end: number | null;
}

export interface ApplyItem {
  id: string;
  original: string;
  proposed: string;
}

// An accepted change sent with the shorten prompt, with its context so Claude can keep it.
export interface FitItem extends ApplyItem {
  section: string;
  kind: string;
  rationale: string;
  keywords: string[];
}

export class ApiError extends Error {
  status: number;
  detail: any;
  constructor(status: number, detail: any) {
    super(typeof detail === "string" ? detail : detail?.message || `Request failed (${status})`);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: init?.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(0, `Cannot reach the backend at ${API_URL}. Is it running?`);
  }
  const body = res.headers.get("content-type")?.includes("json") ? await res.json() : await res.text();
  if (!res.ok) throw new ApiError(res.status, body?.detail ?? body);
  return body as T;
}

export const api = {
  health: () => request<{ latex_available: boolean; latex_engine: string }>("/api/health"),

  getResume: () => request<{ tex: string }>("/api/resume"),
  saveResume: (tex: string, force = false) =>
    request<{ pages: number | null; warning: string | null }>("/api/resume", { method: "PUT", body: JSON.stringify({ tex, force }) }),
  uploadResume: (file: File, force = false) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<{ tex: string; pages: number | null; warning: string | null }>(`/api/resume/upload?force=${force}`, { method: "POST", body: fd });
  },
  history: () => request<{ versions: string[] }>("/api/resume/history"),
  getVersion: (name: string) => request<{ tex: string }>(`/api/resume/history/${encodeURIComponent(name)}`),
  restoreVersion: (name: string) => request<{ tex: string }>(`/api/resume/history/${encodeURIComponent(name)}/restore`, { method: "POST" }),
  baseResumePdfUrl: () => `${API_URL}/api/resume/pdf?t=${Date.now()}`,

  getPrompt: () => request<{ prompt: string; is_default: boolean; default_prompt: string }>("/api/settings/prompt"),
  savePrompt: (prompt: string) =>
    request<{ prompt: string; is_default: boolean; default_prompt: string }>("/api/settings/prompt", { method: "PUT", body: JSON.stringify({ prompt }) }),
  resetPrompt: () => request<{ prompt: string; is_default: boolean; default_prompt: string }>("/api/settings/prompt", { method: "DELETE" }),

  // The app makes no AI calls: these build the prompts you paste into Claude, and check the reply you paste back.
  tailorPrompt: (jd: string) => request<{ prompt: string }>("/api/prompt/tailor", { method: "POST", body: JSON.stringify({ jd }) }),
  fitPrompt: (jd: string, changes: FitItem[], pages: number) =>
    request<{ prompt: string }>("/api/prompt/fit", { method: "POST", body: JSON.stringify({ jd, changes, pages }) }),
  processReply: (text: string) => request<TailorResult>("/api/process", { method: "POST", body: JSON.stringify({ text }) }),
  compile: (changes: ApplyItem[]) => request<CompileResult>("/api/compile", { method: "POST", body: JSON.stringify({ changes }) }),
  // A full document edited by hand in step 5. The base resume is not changed.
  compileTex: (tex: string) => request<CompileResult>("/api/compile/tex", { method: "POST", body: JSON.stringify({ tex }) }),
  // x and y are in PDF points from the page's top-left corner; text is the run of PDF text clicked.
  sourceAt: (id: string, click: { page: number; x: number; y: number; text: string; word: string }) =>
    request<SourceSpot>(
      `/api/output/${id}/source?${new URLSearchParams({ page: String(click.page), x: click.x.toFixed(2), y: click.y.toFixed(2), text: click.text, word: click.word })}`,
    ),
};

export function fileUrl(path: string, download = false, filename?: string) {
  const query = new URLSearchParams();
  if (download) query.set("download", "true");
  if (filename) query.set("filename", filename);
  const qs = query.toString();
  return `${API_URL}${path}${qs ? `?${qs}` : ""}`;
}
