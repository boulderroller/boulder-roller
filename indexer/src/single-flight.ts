/** Coalesce concurrent calls onto one in-flight operation. */
export function singleFlight<T>(operation: () => Promise<T>): () => Promise<T> {
  let active: Promise<T> | null = null;

  return () => {
    if (active) return active;

    let current: Promise<T>;
    try {
      current = Promise.resolve(operation());
    } catch (error) {
      current = Promise.reject(error);
    }
    const clear = () => {
      if (active === current) active = null;
    };
    active = current;
    void current.then(clear, clear);
    return current;
  };
}
