import type { PhilosopherProfile, TurnEvent } from "../types";

/**
 * Base URL of the backend API.
 *
 * Set `VITE_API_URL` at build time to point at a deployed backend
 * (e.g. `https://my-api.onrender.com`). Leave unset in development so the
 * Vite proxy forwards API paths to the local FastAPI server.
 */
const API_BASE = (import.meta.env.VITE_API_URL ?? "").replace(/\/+$/, "");

export interface StreamHandlers {
  onPhilosophers?: (philosophers: PhilosopherProfile[]) => void;
  onStatus?: (message: string) => void;
  onTurn?: (turn: TurnEvent) => void;
  onCooldown?: (usage: CooldownEvent) => void;
  onDone?: (dialogue: string) => void;
  onError?: (message: string) => void;
}

export interface CooldownEvent {
  remaining_seconds: number;
  available_at: string | null;
  daily_request_count: number;
  daily_limit: number;
  daily_remaining: number;
  daily_reset_at: string | null;
  total_requests: number;
  limit_reason?: string | null;
}

export interface DebateStream {
  cancel: () => void;
  finished: Promise<void>;
}

function dispatchSSE(raw: string, handlers: StreamHandlers): void {
  let event: string | null = null;
  const dataLines: string[] = [];

  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }

  const payload = dataLines.join("\n");
  if (!payload) return;

  let data: unknown;
  try {
    data = JSON.parse(payload);
  } catch {
    return;
  }

  switch (event) {
    case "philosophers": {
      const d = data as { philosophers?: PhilosopherProfile[] };
      handlers.onPhilosophers?.(d.philosophers ?? []);
      break;
    }
    case "status": {
      const d = data as { message?: string };
      handlers.onStatus?.(d.message ?? "");
      break;
    }
    case "turn":
      handlers.onTurn?.(data as TurnEvent);
      break;
    case "cooldown": {
      handlers.onCooldown?.(data as CooldownEvent);
      break;
    }
    case "done": {
      const d = data as { dialogue?: string };
      handlers.onDone?.(d.dialogue ?? "");
      break;
    }
    case "error": {
      const d = data as { message?: string };
      handlers.onError?.(d.message ?? "Unknown error");
      break;
    }
  }
}

/**
 * Stream a debate from `POST /debate/stream` by parsing the
 * Server-Sent Events from the response body incrementally.
 */
export function streamDebate(
  topic: string,
  accessToken: string,
  handlers: StreamHandlers,
): DebateStream {
  const controller = new AbortController();

  const finished = (async () => {
    try {
      const res = await fetch(`${API_BASE}/debate/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify({ topic }),
        signal: controller.signal,
      });

      if (!res.ok || !res.body) {
        let message = `Request failed: ${res.status} ${res.statusText}`;
        let retryAfterSeconds = Number(res.headers.get("Retry-After")) || 0;
        try {
          const body = await res.json();
          if (typeof body.detail === "string") message = body.detail;
          else if (Array.isArray(body.detail)) {
            message = body.detail
              .map((issue: { msg?: string }) => issue.msg)
              .filter(Boolean)
              .join("; ") || message;
          }
          else if (body.detail && typeof body.detail === "object") {
            message = body.detail.message ?? message;
            retryAfterSeconds = body.detail.retry_after_seconds ?? retryAfterSeconds;
            handlers.onCooldown?.({
              remaining_seconds: retryAfterSeconds,
              available_at: body.detail.available_at ?? null,
              daily_request_count: body.detail.daily_request_count ?? 0,
              daily_limit: body.detail.daily_limit ?? 5,
              daily_remaining: body.detail.daily_remaining ?? 0,
              daily_reset_at: body.detail.daily_reset_at ?? null,
              total_requests: body.detail.total_requests ?? 0,
              limit_reason: body.detail.limit_reason ?? null,
            });
          }
        } catch {
          // Retain the HTTP status message when the response has no JSON body.
        }
        handlers.onError?.(message);
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let separator: number;
        while ((separator = buffer.indexOf("\n\n")) !== -1) {
          const rawEvent = buffer.slice(0, separator).replace(/\r\n/g, "\n");
          buffer = buffer.slice(separator + 2);
          dispatchSSE(rawEvent, handlers);
        }
      }

      const rawEvent = buffer.replace(/\r\n/g, "\n").trim();
      if (rawEvent) dispatchSSE(rawEvent, handlers);
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        handlers.onError?.((err as Error).message ?? "Stream failed");
      }
    }
  })();

  return { cancel: () => controller.abort(), finished };
}