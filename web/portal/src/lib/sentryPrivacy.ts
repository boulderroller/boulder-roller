// Mirrors backend/app/services/sentry_privacy.py. Unstructured text may contain
// names: keep diagnostic ids, status codes and source locations, not payloads.
type Row = Record<string, unknown>;
const row = (value: unknown): Row => value && typeof value === 'object' && !Array.isArray(value) ? value as Row : {};
const opaqueId = /^(?:[0-9a-f]{16,32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$/i;
const routeParts = new Set('api v1 v2 auth invite validate verify privy admin access geocoding search privacy zones settings users me rides media init complete followers following compliance export account preflight status health profile avatar notifications'.split(' '));
const ids = new Set('id user_id ride_id media_id object_id request_id event_id trace_id span_id parent_span_id'.split(' '));
const statusKeys = new Set('status_code http.status_code status response.status_code'.split(' '));
const enums: Record<string, Set<string>> = Object.fromEntries(Object.entries({
  level: 'fatal error warning info debug log',
  method: 'GET POST PUT PATCH DELETE HEAD OPTIONS',
  op: 'http.client http.server db db.sql.query navigation pageload ui.action queue.task',
  category: 'http fetch xhr console navigation ui.click ui.input',
  type: 'http default navigation user system error',
  status: 'ok unknown_error internal_error invalid_argument not_found unavailable cancelled deadline_exceeded',
  error_code: 'storage_uploaded storage_upload_failed storage_downloaded storage_download_failed storage_signed storage_sign_failed storage_absent storage_deleted storage_delete_failed storage_size_failed storage_check_failed storage_upload_signed storage_upload_sign_failed auth_identity_conflict',
}).map(([key, values]) => [key, new Set(values.split(' '))]));
enums['http.method'] = enums.method;
const isErrorType = (value: unknown): value is string => typeof value === 'string' && /^(?:[A-Za-z_][A-Za-z_0-9]{0,80})?(?:Error|Exception|Timeout)$/.test(value);

function safeUrl(value: unknown): string | undefined {
  if (typeof value !== 'string') return;
  try {
    const relative = value.startsWith('/');
    const url = new URL(value, 'https://local.invalid');
    if (!['https:', 'http:'].includes(url.protocol)) return;
    const path = url.pathname.split('/').map(part => !part || routeParts.has(part) || opaqueId.test(part) ? part : '[Filtered]').join('/');
    return (relative ? '' : `${url.protocol}//${url.hostname}`) + path;
  } catch { return; }
}

function diagnostics(value: unknown): Row {
  const result: Row = {};
  for (const [key, item] of Object.entries(row(value))) {
    if (ids.has(key) && typeof item === 'string' && opaqueId.test(item)) result[key] = item;
    else if (statusKeys.has(key) && typeof item === 'number' && Number.isInteger(item) && item >= 100 && item <= 599) result[key] = item;
    else if (typeof item === 'string' && enums[key]?.has(item)) result[key] = item;
    else if (key === 'error_type' && isErrorType(item)) result[key] = item;
    else if (key === 'url' || key === 'http.url') {
      const url = safeUrl(item);
      if (url !== undefined) result[key] = url;
    }
  }
  return result;
}

function timing(value: Row): Row {
  return Object.fromEntries(['start_timestamp', 'timestamp'].filter(key => {
    const item = value[key];
    return (typeof item === 'number' && Number.isFinite(item)) || (typeof item === 'string'
      && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(item) && Number.isFinite(Date.parse(item)));
  }).map(key => [key, value[key]]));
}

function componentStack(value: unknown): string {
  if (typeof value !== 'string') return '';
  return value.split('\n').flatMap(line => {
    const match = /^\s*(?:at|in) ([A-Za-z_$][\w.$]*)(?:\s|$)/.exec(line);
    if (!match) return [];
    const location = /\(([^()]+\.(?:tsx?|jsx?))(?::(\d+):(\d+))?\)$/.exec(line);
    return [`    at ${match[1]}${location ? ` (${sourcePath(location[1])}${location[2] ? `:${location[2]}:${location[3]}` : ''})` : ''}`];
  }).join('\n');
}

function sourcePath(value: string): string {
  try {
    const path = decodeURIComponent(new URL(value, 'https://local.invalid').pathname);
    const parts = path.split('/');
    const dirs = new Set('src app routes services components lib backend web portal assets static build'.split(' '));
    const clean = parts.map((part, index) => !part || dirs.has(part) || (index === parts.length - 1 && /^[\w.-]+\.(?:py|js|mjs|cjs|ts|tsx|jsx|swift|rs)$/.test(part)) ? part : '[Filtered]').join('/');
    return value.startsWith('/') || value.includes('://') ? clean : clean.replace(/^\//, '');
  } catch { return '[Filtered]'; }
}

function stacktrace(value: unknown): Row {
  const frames = row(value).frames;
  return { frames: Array.isArray(frames) ? frames.map(value => {
    const frame = row(value);
    const clean: Row = {};
    for (const key of ['function', 'module', 'lineno', 'colno', 'in_app']) if (key in frame) clean[key] = frame[key];
    for (const key of ['filename', 'abs_path']) {
      const path = frame[key];
      if (typeof path === 'string') clean[key] = sourcePath(path);
    }
    return clean;
  }) : [] };
}

export function scrubSentryEvent<T extends object>(event: T): T {
  const source = row(event);
  const result: Row = {};
  for (const key of ['event_id', 'timestamp', 'start_timestamp', 'platform', 'level', 'release', 'dist', 'environment', 'logger', 'type']) {
    if (key in source) result[key] = source[key];
  }
  for (const key of ['extra', 'tags', 'user', 'request']) if (key in source) result[key] = diagnostics(source[key]);
  if (row(source.extra).componentStack) (result.extra as Row).componentStack = componentStack(row(source.extra).componentStack);
  if ('contexts' in source) {
    const contexts = row(source.contexts);
    result.contexts = Object.fromEntries(['trace', 'response'].filter(key => key in contexts).map(key => [key, diagnostics(contexts[key])]));
    if (row(contexts.react).componentStack) (result.contexts as Row).react = { componentStack: componentStack(row(contexts.react).componentStack) };
  }
  if ('transaction' in source) result.transaction = safeUrl(source.transaction) ?? '[Filtered]';
  const exceptions = row(source.exception).values;
  if (Array.isArray(exceptions)) result.exception = { values: exceptions.map(value => {
    const exception = row(value);
    const clean: Row = isErrorType(exception.type) ? { type: exception.type } : {};
    const mechanism = row(exception.mechanism);
    if (typeof mechanism.handled === 'boolean') clean.mechanism = { type: 'generic', handled: mechanism.handled };
    if ('stacktrace' in exception) clean.stacktrace = stacktrace(exception.stacktrace);
    return clean;
  }) };
  if ('stacktrace' in source) result.stacktrace = stacktrace(source.stacktrace);
  for (const key of ['breadcrumbs', 'spans']) {
    const values = source[key];
    if (Array.isArray(values)) result[key] = values.map(value => ({ ...diagnostics(value), ...timing(row(value)), data: diagnostics(row(value).data) }));
  }
  const threads = row(source.threads).values;
  if (Array.isArray(threads)) result.threads = { values: threads.map(value => ({ stacktrace: stacktrace(row(value).stacktrace) })) };
  return result as T;
}
