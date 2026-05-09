import { test } from 'node:test';
import assert from 'node:assert/strict';
import { inr, pct, score, relativeTime, shortVerdict } from './format.ts';

test('inr handles common cases', () => {
    assert.equal(inr(1234), '₹1,234');
    assert.equal(inr(1234.56, { fractionDigits: 2 }), '₹1,234.56');
    assert.equal(inr(null), '—');
    assert.equal(inr(undefined), '—');
    assert.equal(inr(NaN), '—');
});

test('pct handles signed and unsigned', () => {
    assert.equal(pct(15.234), '15.2%');
    assert.equal(pct(15.234, { signed: true }), '+15.2%');
    assert.equal(pct(-3.5), '-3.5%');
    assert.equal(pct(-3.5, { signed: true }), '-3.5%');  // negative numbers keep their sign without '+'
    assert.equal(pct(null), '—');
});

test('score formats to one decimal', () => {
    assert.equal(score(7.249), '7.2');
    assert.equal(score(0), '0.0');
    assert.equal(score(null), '—');
});

test('relativeTime returns coarse buckets', () => {
    const now = new Date('2026-05-08T12:00:00Z');
    assert.equal(relativeTime(new Date('2026-05-08T12:00:00Z').toISOString(), now), 'just now');
    assert.equal(relativeTime(new Date('2026-05-08T11:55:00Z').toISOString(), now), '5m ago');
    assert.equal(relativeTime(new Date('2026-05-08T09:00:00Z').toISOString(), now), '3h ago');
    assert.equal(relativeTime(new Date('2026-05-06T12:00:00Z').toISOString(), now), '2d ago');
    assert.equal(relativeTime(undefined, now), '');
    assert.equal(relativeTime('invalid date', now), '');
});

test('shortVerdict swaps underscore for space', () => {
    assert.equal(shortVerdict('STRONG_BUY'), 'STRONG BUY');
    assert.equal(shortVerdict('HOLD'), 'HOLD');
    assert.equal(shortVerdict(null), '');
});
