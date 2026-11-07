export const COMPATIBILITY_RPC_RETRY_MS = 10 * 60_000;
export const SNAPSHOT_RPC_RETRY_MS = 2 * 60_000;

type TransientRpcErrorClass =
  | 'rate_limit'
  | 'minimum_context_slot'
  | 'timeout'
  | 'connection_reset'
  | 'http_5xx';

type RpcError = {
  message?: unknown;
  name?: unknown;
  code?: unknown;
  status?: unknown;
  statusCode?: unknown;
  response?: { status?: unknown };
  cause?: unknown;
};

/** Unknown errors stay fatal; inspect causes for Node fetch transport errors. */
export function transientRpcErrorClass(error: unknown): TransientRpcErrorClass | null {
  const seen = new Set<unknown>();
  while (error != null && !seen.has(error)) {
    seen.add(error);
    const detail: RpcError = typeof error === 'object' ? error : {};
    const message = typeof error === 'string' ? error : String(detail.message ?? '');
    // web3.js exposes HTTP failures as "<status> <statusText>: <body>".
    const httpStatus = message.match(/(?:^|:\s*|\bHTTP(?:\/[\d.]+)?\s+)(429|5\d\d)\b/i)?.[1];
    const status = Number(detail.status ?? detail.statusCode ?? detail.response?.status ?? httpStatus);
    if (status === 429 || /\bmax usage reached\b/i.test(message)) return 'rate_limit';
    if (detail.code === -32016 || /minimum context slot has not been reached/i.test(message)) {
      return 'minimum_context_slot';
    }
    if (status >= 500 && status <= 599) return 'http_5xx';
    const code = String(detail.code ?? '');
    if (detail.name === 'TimeoutError'
      || /^(ETIMEDOUT|ESOCKETTIMEDOUT|UND_ERR_(CONNECT|HEADERS|BODY)_TIMEOUT)$/.test(code)
      || /\b(timed out|timeout|ETIMEDOUT|ESOCKETTIMEDOUT)\b/i.test(message)) return 'timeout';
    if (/^(ECONNRESET|UND_ERR_SOCKET)$/.test(code)
      || /\b(connection reset|socket hang up|ECONNRESET)\b/i.test(message)) return 'connection_reset';
    error = detail.cause;
  }
  return null;
}

/** Retry reads only. A shared deadline bounds all snapshot account-type waits. */
export async function retryTransientRpc<T>(
  read: () => Promise<T>,
  { label, deadline }: { label: string; deadline: number }
): Promise<T> {
  let backoffMs = 1_000;
  for (;;) {
    try {
      return await read();
    } catch (error) {
      const errorClass = transientRpcErrorClass(error);
      const remainingMs = deadline - Date.now();
      if (!errorClass || remainingMs <= 0) throw error;

      // Equal jitter: half to all of the exponentially growing, capped delay.
      const waitMs = Math.min(remainingMs, Math.floor(backoffMs * (0.5 + Math.random() / 2)));
      // Do not log provider error bodies: they can contain endpoint credentials.
      console.warn(`[RPC] ${label}: ${errorClass}; waiting ${waitMs}ms before retry (budget ${remainingMs}ms)`);
      await new Promise<void>((resolve) => setTimeout(resolve, waitMs));
      if (Date.now() >= deadline) throw error;
      backoffMs = Math.min(backoffMs * 2, 30_000);
    }
  }
}
