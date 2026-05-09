'use client';

import { useState } from 'react';
import { Link2, Check } from 'lucide-react';

interface ShareButtonProps {
    runId: string | null;
    disabled?: boolean;
}

export function ShareButton({ runId, disabled }: ShareButtonProps) {
    const [copied, setCopied] = useState(false);

    async function handleCopy() {
        if (!runId) return;
        const url = `${window.location.origin}/verdict/${encodeURIComponent(runId)}`;
        try {
            if (navigator.clipboard && window.isSecureContext) {
                await navigator.clipboard.writeText(url);
            } else {
                // Fallback for http://localhost or older browsers
                const ta = document.createElement('textarea');
                ta.value = url;
                ta.setAttribute('readonly', '');
                ta.style.position = 'absolute';
                ta.style.left = '-9999px';
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
            }
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1800);
        } catch {
            // Soft-fail; user can grab the URL from the address bar of /verdict/{id}
        }
    }

    const isDisabled = disabled || !runId;

    return (
        <button
            onClick={handleCopy}
            disabled={isDisabled}
            title={isDisabled ? 'Available once the verdict is complete' : 'Copy a permalink to this verdict'}
            className={`inline-flex items-center gap-1.5 text-[12px] font-medium px-2.5 py-1.5 rounded-md border transition cursor-pointer
                ${copied
                    ? 'border-[#15803D] bg-[#ECFDF3] text-[#15803D]'
                    : 'border-[#E5E3DB] bg-white text-[#4A4D55] hover:border-[#C6C3B8]'}
                disabled:opacity-50 disabled:cursor-not-allowed`}
        >
            {copied ? <Check size={14} /> : <Link2 size={14} />}
            {copied ? 'Link copied' : 'Share'}
        </button>
    );
}
