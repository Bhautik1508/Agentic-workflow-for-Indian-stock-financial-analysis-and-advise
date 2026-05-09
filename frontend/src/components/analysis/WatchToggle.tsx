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
                    ? 'border-[#1E40AF] bg-[#F0F4FB] text-[#1E40AF]'
                    : 'border-[#E5E3DB] bg-white text-[#4A4D55] hover:border-[#C6C3B8]'}`}
        >
            {watched ? <BookmarkCheck size={14} /> : <Bookmark size={14} />}
            {watched ? 'Watching' : 'Watch'}
        </button>
    );
}
