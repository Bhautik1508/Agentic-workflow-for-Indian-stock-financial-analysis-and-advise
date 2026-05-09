// Tiny formatting primitives used across the editorial verdict UI.
// All functions are pure + null-safe so they can render mid-stream when
// only some fields have arrived from the SSE feed.

export function inr(value: number | null | undefined, opts?: { fractionDigits?: number }): string {
    if (value === null || value === undefined || Number.isNaN(value)) return '—';
    const fd = opts?.fractionDigits ?? 0;
    return `₹${value.toLocaleString('en-IN', { minimumFractionDigits: fd, maximumFractionDigits: fd })}`;
}

export function pct(value: number | null | undefined, opts?: { fractionDigits?: number; signed?: boolean }): string {
    if (value === null || value === undefined || Number.isNaN(value)) return '—';
    const fd = opts?.fractionDigits ?? 1;
    const sign = opts?.signed && value > 0 ? '+' : '';
    return `${sign}${value.toFixed(fd)}%`;
}

export function score(value: number | null | undefined): string {
    if (value === null || value === undefined || Number.isNaN(value)) return '—';
    return value.toFixed(1);
}

export function relativeTime(iso: string | null | undefined, now: Date = new Date()): string {
    if (!iso) return '';
    const then = new Date(iso);
    if (Number.isNaN(then.getTime())) return '';
    const diff = now.getTime() - then.getTime();
    const m = Math.floor(diff / 60_000);
    const h = Math.floor(diff / 3_600_000);
    const d = Math.floor(diff / 86_400_000);
    if (d >= 1) return `${d}d ago`;
    if (h >= 1) return `${h}h ago`;
    if (m >= 1) return `${m}m ago`;
    return 'just now';
}

export function shortVerdict(verdict: string | null | undefined): string {
    if (!verdict) return '';
    return verdict.replace('_', ' ');
}
