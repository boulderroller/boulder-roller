export const lookupStorageKey = (id: string, wallet: string) => `br-stage1-lookups:${id}:${wallet}`;

export function saveLookup(key: string, table: string, remove = false) {
  const previous: string[] = JSON.parse(sessionStorage.getItem(key) ?? '[]');
  sessionStorage.setItem(key, JSON.stringify(remove ? previous.filter(t => t !== table) : [...new Set([...previous, table])]));
  window.dispatchEvent(new Event('stage1-lookups'));
}

export function clearClaimLookup(id: string, wallet: string, table: string) {
  const prefix = ['br-stage1-operation', id, wallet, 'self-claim', ''].join(':');
  for (const key of Object.keys(sessionStorage)) {
    if (key.startsWith(prefix) && key.endsWith(':lookup') && sessionStorage.getItem(key) === table) sessionStorage.removeItem(key);
  }
}
