/**
 * The visitor id: one private demo inbox per visitor (decided 2026-11-13).
 *
 * WHAT HAPPENS: the first time the page opens, it makes a random id (crypto.randomUUID(), built into
 * browsers) and saves it in the browser's localStorage (a small key -> text store that belongs to
 * this website and survives reloads). Every request to the backend carries it in the header
 * "X-Visitor-Id", and the backend shows this visitor only their own runs and decisions.
 *
 * Example id: "7c1e2b0a-4f5d-4e8a-9a51-3c0d2e9f1b77"
 *
 * localStorage can be blocked (private windows, strict settings): then the id lives only in memory,
 * so the inbox still works, it just starts fresh after a reload. Not a login and not security: anyone
 * with the same id sees the same (fake) demo inbox.
 */

const STORAGE_KEY = "overlook-visitor-id";

let idInMemory: string | null = null;      // used if localStorage is blocked

export function visitorId(): string {
  if (idInMemory !== null) return idInMemory;
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved !== null) {
      idInMemory = saved;
      return saved;
    }
  } catch {
    // localStorage blocked: fall through and make an id for this page only
  }
  const id = crypto.randomUUID();
  idInMemory = id;
  try {
    localStorage.setItem(STORAGE_KEY, id);
  } catch {
    // blocked: the id stays in memory only
  }
  return id;
}
