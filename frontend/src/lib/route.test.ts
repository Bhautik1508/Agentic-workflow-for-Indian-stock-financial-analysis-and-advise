import { strict as assert } from 'node:assert';
import { test } from 'node:test';

import { decodeRouteParam, toRouteTicker } from './route.ts';

test('decodeRouteParam decodes a percent-encoded space exactly once', () => {
    // The bug: passing the raw param to a URL builder that encodes again
    // produced HDFC%2520Bank, and the API received the literal "HDFC%20Bank".
    assert.equal(decodeRouteParam('HDFC%20Bank'), 'HDFC Bank');
    assert.equal(decodeRouteParam('Bajaj%20Finance'), 'Bajaj Finance');
});

test('decodeRouteParam leaves plain symbols untouched', () => {
    assert.equal(decodeRouteParam('HDFCBANK'), 'HDFCBANK');
    assert.equal(decodeRouteParam('TCS'), 'TCS');
});

test('decodeRouteParam does not decode twice', () => {
    // %2520 -> %20, and must stop there rather than becoming a space.
    assert.equal(decodeRouteParam('HDFC%2520Bank'), 'HDFC%20Bank');
});

test('decodeRouteParam survives malformed encoding', () => {
    // decodeURIComponent throws URIError here; a bad URL must not blank the page.
    assert.equal(decodeRouteParam('100%'), '100%');
    assert.equal(decodeRouteParam('%E0%A4'), '%E0%A4');
});

test('decodeRouteParam handles empty input', () => {
    assert.equal(decodeRouteParam(''), '');
});

test('toRouteTicker strips exchange suffixes like SearchBar does', () => {
    assert.equal(toRouteTicker('HDFCBANK.NS'), 'HDFCBANK');
    assert.equal(toRouteTicker('RELIANCE.BO'), 'RELIANCE');
    assert.equal(toRouteTicker('bajfinance.ns'), 'bajfinance');
});

test('toRouteTicker leaves a bare symbol alone', () => {
    assert.equal(toRouteTicker('TCS'), 'TCS');
});

test('quick-pick and search produce the same route for the same stock', () => {
    // The original defect: the pill navigated by display name while search
    // navigated by symbol, so only one of the two paths worked.
    const fromPill = toRouteTicker('HDFCBANK.NS');
    const fromSearch = 'HDFCBANK.NS'.replace('.NS', '').replace('.BO', '');
    assert.equal(fromPill, fromSearch);
});
