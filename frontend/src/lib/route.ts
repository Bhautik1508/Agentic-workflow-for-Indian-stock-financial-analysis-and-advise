/**
 * Route-parameter helpers.
 *
 * Next.js App Router hands `params` back as the RAW url segment — it is not
 * decoded for you. Passing that straight into a `fetch` URL that then calls
 * `encodeURIComponent` double-encodes it: `/analyze/HDFC%20Bank` becomes
 * `HDFC%2520Bank`, and the API receives the literal text "HDFC%20Bank" as the
 * company name, which resolves to nothing.
 *
 * It only shows up for names containing a character that needs encoding, which
 * is why "HDFC Bank" and "Bajaj Finance" failed while "TCS" and "Wipro" were
 * fine — for those, encodeURIComponent is a no-op.
 */

/**
 * Decode a route param exactly once, safely.
 *
 * Returns the input unchanged if it is not valid percent-encoding —
 * `decodeURIComponent` throws a URIError on a bare "%", and a malformed URL
 * should not blank the page.
 */
export function decodeRouteParam(raw: string): string {
    if (!raw) return '';
    try {
        return decodeURIComponent(raw);
    } catch {
        return raw;
    }
}

/**
 * Normalise a symbol or company name into the form used in URLs.
 *
 * Mirrors what SearchBar already does with results (`RELIANCE.NS` ->
 * `RELIANCE`) so a quick-pick link and a search result navigate to exactly the
 * same place, instead of one sending a symbol and the other a display name.
 */
export function toRouteTicker(tickerOrName: string): string {
    return (tickerOrName || '').replace(/\.(NS|BO)$/i, '');
}
