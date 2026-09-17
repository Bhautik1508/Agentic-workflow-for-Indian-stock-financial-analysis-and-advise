'use client';

import { Printer } from 'lucide-react';

export function PrintButton() {
    function handlePrint() {
        if (typeof window !== 'undefined') {
            window.print();
        }
    }
    return (
        <button
            onClick={handlePrint}
            title="Print or save as PDF"
            className="inline-flex items-center gap-1.5 text-[12px] font-medium px-2.5 py-1.5 rounded-md border border-rule bg-white text-ink-2 hover:border-rule-strong transition cursor-pointer"
        >
            <Printer size={14} />
            Print
        </button>
    );
}
