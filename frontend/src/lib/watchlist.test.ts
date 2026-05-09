import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
    addToWatchlist,
    clearWatchlist,
    isWatched,
    loadWatchlist,
    MAX_WATCHLIST,
    removeFromWatchlist,
    saveWatchlist,
    toggleWatchlist,
    type WatchlistEntry,
} from './watchlist.ts';

class FakeStorage {
    private store = new Map<string, string>();
    getItem(key: string): string | null { return this.store.get(key) ?? null; }
    setItem(key: string, value: string): void { this.store.set(key, value); }
    removeItem(key: string): void { this.store.delete(key); }
}

function fresh(): FakeStorage { return new FakeStorage(); }

test('loadWatchlist returns empty array when storage is empty', () => {
    assert.deepEqual(loadWatchlist(fresh()), []);
});

test('addToWatchlist persists a new entry', () => {
    const s = fresh();
    const out = addToWatchlist('Reliance', s);
    assert.equal(out.length, 1);
    assert.equal(out[0].name, 'Reliance');
    assert.ok(out[0].addedAt);
    assert.deepEqual(loadWatchlist(s).map(e => e.name), ['Reliance']);
});

test('addToWatchlist deduplicates case-insensitively and pulls to top', () => {
    const s = fresh();
    addToWatchlist('Reliance', s);
    addToWatchlist('TCS', s);
    addToWatchlist('reliance', s);   // case difference
    const list = loadWatchlist(s);
    assert.equal(list.length, 2);
    assert.equal(list[0].name, 'reliance');   // re-added → at top with new casing
    assert.equal(list[1].name, 'TCS');
});

test('addToWatchlist trims whitespace and ignores empty', () => {
    const s = fresh();
    addToWatchlist('  Reliance  ', s);
    const list = loadWatchlist(s);
    assert.equal(list[0].name, 'Reliance');

    addToWatchlist('   ', s);
    addToWatchlist('', s);
    assert.equal(loadWatchlist(s).length, 1);
});

test('addToWatchlist caps at MAX_WATCHLIST', () => {
    const s = fresh();
    for (let i = 0; i < MAX_WATCHLIST + 5; i++) {
        addToWatchlist(`Stock-${i}`, s);
    }
    assert.equal(loadWatchlist(s).length, MAX_WATCHLIST);
    // Most-recent first, so Stock-(MAX+4) is at the top
    assert.equal(loadWatchlist(s)[0].name, `Stock-${MAX_WATCHLIST + 4}`);
});

test('removeFromWatchlist removes by name (case-insensitive)', () => {
    const s = fresh();
    addToWatchlist('Reliance', s);
    addToWatchlist('TCS', s);
    removeFromWatchlist('reliance', s);
    const list = loadWatchlist(s);
    assert.equal(list.length, 1);
    assert.equal(list[0].name, 'TCS');
});

test('isWatched returns boolean for known/unknown', () => {
    const s = fresh();
    addToWatchlist('Reliance', s);
    assert.equal(isWatched('Reliance', s), true);
    assert.equal(isWatched('reliance', s), true);   // case-insensitive
    assert.equal(isWatched('Wipro', s), false);
});

test('toggleWatchlist round-trips', () => {
    const s = fresh();
    toggleWatchlist('Reliance', s);
    assert.equal(isWatched('Reliance', s), true);
    toggleWatchlist('Reliance', s);
    assert.equal(isWatched('Reliance', s), false);
});

test('clearWatchlist empties storage', () => {
    const s = fresh();
    addToWatchlist('Reliance', s);
    addToWatchlist('TCS', s);
    clearWatchlist(s);
    assert.deepEqual(loadWatchlist(s), []);
});

test('loadWatchlist tolerates corrupted storage', () => {
    const s = fresh();
    s.setItem('stocksage_watchlist', 'not valid json {');
    assert.deepEqual(loadWatchlist(s), []);

    s.setItem('stocksage_watchlist', '"a string, not an array"');
    assert.deepEqual(loadWatchlist(s), []);

    s.setItem('stocksage_watchlist', '[{"missing": "name"}]');
    assert.deepEqual(loadWatchlist(s), []);
});

test('saveWatchlist + loadWatchlist round-trip is stable', () => {
    const s = fresh();
    const entries: WatchlistEntry[] = [
        { name: 'A', addedAt: '2026-01-01T00:00:00Z' },
        { name: 'B', addedAt: '2026-01-02T00:00:00Z' },
    ];
    saveWatchlist(entries, s);
    const loaded = loadWatchlist(s);
    assert.deepEqual(loaded.map(e => e.name), ['A', 'B']);
});
