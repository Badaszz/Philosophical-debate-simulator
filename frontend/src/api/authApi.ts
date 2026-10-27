export interface UserProfile {
  email: string;
  is_admin: boolean;
  rate_limit_exempt: boolean;
  remaining_seconds: number;
  available_at: string | null;
  total_requests: number;
  daily_request_count: number;
  daily_limit: number;
  daily_remaining: number;
  daily_reset_at: string;
}

export interface AdminState {
  restrict_sign_in: boolean;
  allowed_users: string[];
}

const API_BASE = (import.meta.env.VITE_API_URL ?? "").replace(/\/+$/, "");

export async function apiRequest<T>(
  path: string,
  accessToken: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
      ...init.headers,
    },
  });

  if (!response.ok) {
    let message = `Request failed: ${response.status} ${response.statusText}`;
    try {
      const body: {
        detail?: string | { message?: string };
      } = await response.json();
      if (typeof body.detail === "string") message = body.detail;
      else if (body.detail) message = body.detail.message ?? message;
    } catch {
      // Retain the HTTP status message when the response has no JSON body.
    }
    throw new Error(message);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
