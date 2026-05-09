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
            className="inline-flex items-center gap-1.5 text-[12px] font-medium px-2.5 py-1.5 rounded-md border border-[#E5E3DB] bg-white text-[#4A4D55] hover:border-[#C6C3B8] transition cursor-pointer"
        >
            <Printer size={14} />
            Print
        </button>
    );
}
