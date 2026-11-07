import { createContext, useContext, useLayoutEffect, useState, type ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { browserRoom, composeBrowserTitle } from '../lib/browserTitle';

type TitleObject = { pathname: string; name: string | null };
const BrowserTitleContext = createContext<((object: TitleObject) => void) | null>(null);

export function BrowserTitleProvider({ children }: { children: ReactNode }) {
  // Routes supplies the underlying room location while Upload is open.
  const { pathname, search } = useLocation();
  const [object, setObject] = useState<TitleObject | null>(null);
  const room = browserRoom(pathname, search);
  const name = object?.pathname === pathname ? object.name : null;
  useLayoutEffect(() => {
    if (pathname !== '/upload') document.title = composeBrowserTitle(name, room);
  }, [name, pathname, room]);
  return <BrowserTitleContext.Provider value={setObject}>{children}</BrowserTitleContext.Provider>;
}

/** Rooms contribute only data already loaded for the current object. */
export function useBrowserTitleObject(name: string | null) {
  const setObject = useContext(BrowserTitleContext);
  const { pathname } = useLocation();
  useLayoutEffect(() => {
    setObject?.({ pathname, name });
    return () => setObject?.({ pathname, name: null });
  }, [name, pathname, setObject]);
}

export function useBrowserTitle(room: string, object: string | null = null) {
  useLayoutEffect(() => {
    document.title = composeBrowserTitle(object, room);
  }, [object, room]);
}
