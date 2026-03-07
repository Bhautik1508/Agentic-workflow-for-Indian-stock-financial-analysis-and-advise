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
                const res = await fetch(`http://localhost:8000/api/search/${encodeURIComponent(query)}`);
                if (res.ok) {
                    const data = await res.json();
                    setResults(data.results || []);
                } else {
                    setResults([]);
                }
            } catch (err) {
                console.error(err);
                setResults([]);
            } finally {
                setIsLoading(false);
            }
        }, 500); // 500ms debounce

        return () => clearTimeout(timer);
    }, [query]);

    return { query, setQuery, results, isLoading };
}
