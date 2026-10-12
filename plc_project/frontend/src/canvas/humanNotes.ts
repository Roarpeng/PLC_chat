export type HumanNote = {
  text: string;
  updatedAt: number;
};

const STORAGE_KEY = "researchos.canvas.humanNotes.v1";

function readAll(): Record<string, HumanNote> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, HumanNote>;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

export function noteKey(jobId: string | null | undefined, nodeId: string): string {
  return `${jobId || "local"}:${nodeId}`;
}

export function readHumanNote(key: string): string {
  return String(readAll()[key]?.text || "");
}

export function writeHumanNote(key: string, text: string): HumanNote {
  const next: HumanNote = { text, updatedAt: Date.now() };
  const all = readAll();
  if (text.trim()) all[key] = next;
  else delete all[key];
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(all));
  } catch {
    /* quota / private mode */
  }
  return next;
}
