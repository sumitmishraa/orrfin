/**
 * Where the browser finds the Orrfin API. Set NEXT_PUBLIC_API_URL in the environment
 * (scripts/dev.ps1 passes it from the repo-root .env); defaults to the local API.
 */
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
