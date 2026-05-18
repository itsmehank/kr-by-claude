const API_BASE = "/api";

export async function api<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    const err = new Error(`API ${path} failed: ${res.status}`) as Error & { status: number };
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}
