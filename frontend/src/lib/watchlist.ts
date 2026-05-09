// localStorage-backed watchlist for Phase 5.
// Server-side persistence (per-user, with diff alerts) is Phase 6.

const STORAGE_KEY = 'stocksage_watchlist';
export const MAX_WATCHLIST = 25;

export interface WatchlistEntry {
    name:        string;       // display + search query (e.g. "Reliance")
    addedAt:     string;       // ISO timestamp
}

// SSR-safe localStorage wrapper. Returns sane defaults on the server.
type Storage = Pick<globalThis.Storage, 'getItem' | 'setItem' | 'removeItem'>;

function getStorage(): Storage | null {
    if (typeof window === 'undefined') return null;
    try {
        return window.localStorage;
    } catch {
        return null;
    }
}

export function loadWatchlist(storage: Storage | null = getStorage()): WatchlistEntry[] {
    if (!storage) return [];
    try {
        const raw = storage.getItem(STORAGE_KEY);
        if (!raw) return [];
        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) return [];
        return parsed.filter(isValidEntry).slice(0, MAX_WATCHLIST);
    } catch {
        return [];
    }
}

export function saveWatchlist(entries: WatchlistEntry[], storage: Storage | null = getStorage()): void {
    if (!storage) return;
    try {
        storage.setItem(STORAGE_KEY, JSON.stringify(entries.slice(0, MAX_WATCHLIST)));
    } catch {
        // quota exceeded / private mode — ignore silently
    }
}

export function addToWatchlist(name: string, storage: Storage | null = getStorage()): WatchlistEntry[] {
    const trimmed = (name ?? '').trim();
    if (!trimmed) return loadWatchlist(storage);

    const current = loadWatchlist(storage);
    const dedup = current.filter(e => normalize(e.name) !== normalize(trimmed));
    const updated: WatchlistEntry[] = [
        { name: trimmed, addedAt: new Date().toISOString() },
        ...dedup,
    ].slice(0, MAX_WATCHLIST);
    saveWatchlist(updated, storage);
    return updated;
}

export function removeFromWatchlist(name: string, storage: Storage | null = getStorage()): WatchlistEntry[] {
    const target = normalize(name);
    const updated = loadWatchlist(storage).filter(e => normalize(e.name) !== target);
    saveWatchlist(updated, storage);
    return updated;
}

export function isWatched(name: string, storage: Storage | null = getStorage()): boolean {
    const target = normalize(name);
    return loadWatchlist(storage).some(e => normalize(e.name) === target);
}

export function toggleWatchlist(name: string, storage: Storage | null = getStorage()): WatchlistEntry[] {
    return isWatched(name, storage)
        ? removeFromWatchlist(name, storage)
        : addToWatchlist(name, storage);
}

export function clearWatchlist(storage: Storage | null = getStorage()): void {
    if (!storage) return;
    storage.removeItem(STORAGE_KEY);
}

function isValidEntry(e: unknown): e is WatchlistEntry {
    return !!e
        && typeof e === 'object'
        && typeof (e as WatchlistEntry).name === 'string'
        && (e as WatchlistEntry).name.trim().length > 0;
}

function normalize(s: string): string {
    return s.trim().toLowerCase();
}
