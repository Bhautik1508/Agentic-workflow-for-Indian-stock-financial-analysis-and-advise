import { useState, useEffect } from 'react';

export interface SearchResult {
    name: string;
    ticker: string;
}

export function useStockSearch() {
    const [query, setQuery] = useState('');
    const [results, setResults] = useState<SearchResult[]>([]);
    const [isLoading, setIsLoading] = useState(false);

    useEffect(() => {
        if (!query.trim()) {
            setResults([]);
            return;
        }

        const timer = setTimeout(async () => {
            setIsLoading(true);
            try {
                // Here we'd hit our FastAPI backend. For now, we mock some top Indian stocks
                // In reality: const res = await fetch(`http://localhost:8000/api/search/${query}`);
                const dummyResults = [
                    { name: query.toUpperCase() + ' Limited', ticker: query.toUpperCase() + '.NS' },
                    { name: 'Reliance Industries', ticker: 'RELIANCE.NS' },
                    { name: 'Tata Motors', ticker: 'TATAMOTORS.NS' },
                    { name: 'HDFC Bank', ticker: 'HDFCBANK.NS' }
                ].filter(r => r.name.toLowerCase().includes(query.toLowerCase()) || r.ticker.toLowerCase().includes(query.toLowerCase()));

                // If no match in dummy, just return the exact query as a ticker to let the backend resolve it
                if (dummyResults.length === 0) {
                    setResults([{ name: query.toUpperCase(), ticker: query.toUpperCase() + '.NS' }]);
                } else {
                    setResults(dummyResults);
                }
            } catch (err) {
                console.error(err);
            } finally {
                setIsLoading(false);
            }
        }, 400); // 400ms debounce

        return () => clearTimeout(timer);
    }, [query]);

    return { query, setQuery, results, isLoading };
}
