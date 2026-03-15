import { useState, useEffect, useRef } from 'react';
import { getApiUrl } from '@/config';

export interface SearchResult {
    name: string;
    ticker: string;
    exchange: string;
    sector: string;
}

export function useStockSearch() {
    const [query, setQuery] = useState('');
    const [results, setResults] = useState<SearchResult[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const abortRef = useRef<AbortController | null>(null);

    useEffect(() => {
        if (!query.trim() || query.trim().length < 2) {
            setResults([]);
            setIsLoading(false);
            return;
        }

        setIsLoading(true);

        const timer = setTimeout(async () => {
            // Abort any in-flight request
            if (abortRef.current) {
                abortRef.current.abort();
            }
            const controller = new AbortController();
            abortRef.current = controller;

            try {
                const API_BASE_URL = getApiUrl();
                const response = await fetch(
                    `${API_BASE_URL}/api/search/${encodeURIComponent(query.trim())}`,
                    { signal: controller.signal }
                );
                if (response.ok) {
                    const data = await response.json();
                    setResults(data.results || []);
                } else {
                    setResults([]);
                }
            } catch (err: unknown) {
                if (err instanceof Error && err.name !== 'AbortError') {
                    console.error('Search error:', err);
                    setResults([]);
                }
            } finally {
                if (!controller.signal.aborted) {
                    setIsLoading(false);
                }
            }
        }, 300); // 300ms debounce

        return () => {
            clearTimeout(timer);
            if (abortRef.current) {
                abortRef.current.abort();
            }
        };
    }, [query]);

    return { query, setQuery, results, isLoading };
}
