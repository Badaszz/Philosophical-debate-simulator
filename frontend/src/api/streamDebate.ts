import type { PhilosopherProfile, TurnEvent } from "../types";

/**
 * Base URL of the backend API.
 *
 * Set `VITE_API_URL` at build time to point at a deployed backend
 * (e.g. `https://my-api.onrender.com`). Leave unset in development so the
 * Vite proxy forwards `/debate` to the local FastAPI server.
 */
const API_BASE = (import.meta.env.VITE_API_URL ?? "").replace(/\/+$/, "");

export interface StreamHandlers {
  onPhilosophers?: (philosophers: PhilosopherProfile[]) => void;
  onStatus?: (message: string) => void;
  onTurn?: (turn: TurnEvent) => void;
  onDone?: (dialogue: string) => void;
  onError?: (message: string) => void;
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
export function streamDebate(topic: string, handlers: StreamHandlers): DebateStream {
  const controller = new AbortController();

  const finished = (async () => {
    try {
      const res = await fetch(`${API_BASE}/debate/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic }),
        signal: controller.signal,
      });

      if (!res.ok || !res.body) {
        handlers.onError?.(`Request failed: ${res.status} ${res.statusText}`);
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