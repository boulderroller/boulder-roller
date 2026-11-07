let fallbackSequence = 0;

export const createClientRequestId = (prefix = 'balance') => {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  fallbackSequence += 1;
  return `${prefix}-${Date.now()}-${fallbackSequence}`;
};
