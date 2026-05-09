'use client';

interface MonogramProps {
    name: string;     // e.g. "Financial Analyst"
    size?: number;
}

const COLOURS: Record<string, string> = {
    'Financial Analyst':           '#1E40AF',  // editorial blue
    'Technical Analyst':           '#166534',  // deep green
    'Risk Analyst':                '#991B1B',  // deep red
    'Sentiment Analyst':           '#A16207',  // amber
    'Macro & Governance Analyst':  '#4A4D55',  // ink
};

export function AnalystMonogram({ name, size = 26 }: MonogramProps) {
    const initials = name
        .replace(' Analyst', '')
        .split(/[\s&]+/)
        .filter(Boolean)
        .map(w => w[0])
        .slice(0, 2)
        .join('')
        .toUpperCase();
    const colour = COLOURS[name] ?? '#4A4D55';
    return (
        <span
            className="inline-flex items-center justify-center rounded-full font-serif font-semibold shrink-0"
            style={{
                width: size,
                height: size,
                fontSize: Math.round(size * 0.42),
                background: `${colour}14`,
                color: colour,
                border: `1px solid ${colour}30`,
            }}
            aria-hidden
        >
            {initials || '?'}
        </span>
    );
}
