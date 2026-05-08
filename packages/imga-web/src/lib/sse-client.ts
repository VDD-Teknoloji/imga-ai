// Sprint 9.0.5-B A — reusable Server-Sent Events client.
//
// The browser's native EventSource API doesn't support custom
// HTTP headers; our backend authenticates with
// ``Authorization: Bearer …`` so we'd otherwise have to smuggle
// the token through a query param (visible in proxy logs) or
// switch the entire auth surface to cookies. Neither fits the
// demo deadline.
//
// Instead we use ``fetch()`` with a ``ReadableStream`` body and
// parse the SSE wire format by hand. The format is small:
//
//     event: progress
//     data: {"processed": 123, "total": 5000}
//
//     event: complete
//     data: {…}
//
// (blank line terminates a frame). We accumulate bytes per frame,
// decode on the blank-line boundary, and dispatch to the caller's
// per-event handler map.
//
// Reconnect / backoff:
//   * On a network error or non-2xx response, retry with
//     exponential backoff (1s → 2s → 4s → 8s, capped) up to a
//     handful of attempts.
//   * Caller can ``close()`` the handle to abort and skip any
//     pending retry.

export type SseEventHandler = (payload: unknown) => void;
export type SseHandlerMap = Record<string, SseEventHandler>;

export interface SseClientOptions {
  /** Map of event-name → handler. JSON.parse is attempted on the
   *  ``data:`` payload; on parse failure the raw string is passed
   *  through. */
  handlers: SseHandlerMap;
  /** Called once on the first byte read from the stream. */
  onOpen?: () => void;
  /** Called on a network / parse / non-2xx error. */
  onError?: (error: unknown) => void;
  /** Bearer token for the ``Authorization`` header. */
  token?: string | null;
  /** Set true to auto-reconnect on transport errors. */
  reconnect?: boolean;
}

export interface SseHandle {
  close: () => void;
}

const RECONNECT_BASE_MS = 1_000;
const RECONNECT_CAP_MS = 8_000;
const MAX_RECONNECT_ATTEMPTS = 6;

export function openSseStream(
  url: string,
  options: SseClientOptions,
): SseHandle {
  let abort: AbortController | null = null;
  let attempt = 0;
  let closed = false;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  const dispatch = (eventName: string, raw: string): void => {
    const handler = options.handlers[eventName];
    if (!handler) return;
    if (!raw) {
      handler(null);
      return;
    }
    try {
      handler(JSON.parse(raw));
    } catch {
      handler(raw);
    }
  };

  const consume = async (response: Response): Promise<void> => {
    if (!response.ok) {
      throw new Error(`SSE HTTP ${response.status}`);
    }
    if (response.body === null) {
      throw new Error("SSE response has no body");
    }
    options.onOpen?.();
    attempt = 0;

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      if (closed) {
        await reader.cancel();
        return;
      }
      const { value, done } = await reader.read();
      if (done) return;
      buffer += decoder.decode(value, { stream: true });

      // SSE frames are separated by a blank line. We split on the
      // first \n\n we find and process each complete frame.
      let separator = buffer.indexOf("\n\n");
      while (separator !== -1) {
        const frame = buffer.slice(0, separator);
        buffer = buffer.slice(separator + 2);
        let eventName = "message";
        const dataLines: string[] = [];
        for (const line of frame.split("\n")) {
          if (line.startsWith("event:")) {
            eventName = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            dataLines.push(line.slice(5).trim());
          }
          // ``id:`` and ``retry:`` lines are spec-supported but we
          // don't act on them here; ignore.
        }
        dispatch(eventName, dataLines.join("\n"));
        separator = buffer.indexOf("\n\n");
      }
    }
  };

  const connect = async (): Promise<void> => {
    if (closed) return;
    abort = new AbortController();
    try {
      const response = await fetch(url, {
        signal: abort.signal,
        headers: {
          Accept: "text/event-stream",
          ...(options.token
            ? { Authorization: `Bearer ${options.token}` }
            : {}),
        },
        cache: "no-store",
      });
      await consume(response);
    } catch (err) {
      if (closed) return;
      if (
        err instanceof DOMException && err.name === "AbortError"
      ) {
        return;
      }
      options.onError?.(err);
      if (!options.reconnect) return;
      if (attempt >= MAX_RECONNECT_ATTEMPTS) return;
      const wait = Math.min(
        RECONNECT_BASE_MS * 2 ** attempt,
        RECONNECT_CAP_MS,
      );
      attempt += 1;
      reconnectTimer = setTimeout(() => {
        void connect();
      }, wait);
    }
  };

  void connect();

  return {
    close(): void {
      closed = true;
      if (reconnectTimer !== null) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      if (abort !== null) {
        abort.abort();
        abort = null;
      }
    },
  };
}
