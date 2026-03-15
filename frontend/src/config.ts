export const getApiUrl = (): string => {
    // 1. If the env var is explicitly set (e.g., local dev or custom deployment), use it
    if (process.env.NEXT_PUBLIC_API_URL) {
        return process.env.NEXT_PUBLIC_API_URL;
    }

    // 2. If running in the browser, check the hostname
    if (typeof window !== 'undefined') {
        const hostname = window.location.hostname;
        // If we are on Vercel or any non-local domain, it's production
        if (hostname !== 'localhost' && hostname !== '127.0.0.1') {
            return 'https://agentic-workflow-for-indian-stock.onrender.com';
        }
    }

    // 3. Fallback for server-side rendering or local development
    return 'http://localhost:8000';
};
