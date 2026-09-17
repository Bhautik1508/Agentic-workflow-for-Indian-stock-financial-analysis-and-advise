'use client';

import { useEffect, useState } from 'react';
import { Bookmark, BookmarkCheck } from 'lucide-react';
import { isWatched, toggleWatchlist } from '@/lib/watchlist';

interface WatchToggleProps {
    name: string;
}

export function WatchToggle({ name }: WatchToggleProps) {
    const [watched, setWatched] = useState(false);

    useEffect(() => {
        setWatched(isWatched(name));
    }, [name]);

    function handleToggle() {
        toggleWatchlist(name);
        setWatched(prev => !prev);
    }

    return (
        <button
            onClick={handleToggle}
            aria-pressed={watched}
            title={watched ? 'Remove from watchlist' : 'Add to watchlist'}
            className={`inline-flex items-center gap-1.5 text-[12px] font-medium px-2.5 py-1.5 rounded-md border transition cursor-pointer
                ${watched
                    ? 'border-accent bg-accent-tint text-accent'
                    : 'border-rule bg-white text-ink-2 hover:border-rule-strong'}`}
        >
            {watched ? <BookmarkCheck size={14} /> : <Bookmark size={14} />}
            {watched ? 'Watching' : 'Watch'}
        </button>
    );
}
