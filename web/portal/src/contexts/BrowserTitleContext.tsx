import { createContext, useContext, useLayoutEffect, useState, type ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { browserPageName, composeBrowserTitle } from '../lib/browserTitle';

type TitleObject = { pathname: string; name: string | null };
const BrowserTitleContext = createContext<((object: TitleObject) => void) | null>(null);

export function BrowserTitleProvider({ children }: { children: ReactNode }) {
  // Routes supplies the underlying page location while Upload is open.
  const { pathname, search } = useLocation();
  const [object, setObject] = useState<TitleObject | null>(null);
  const page = browserPageName(pathname, search);
  const name = object?.pathname === pathname ? object.name : null;
  useLayoutEffect(() => {
    if (pathname !== '/upload') document.title = composeBrowserTitle(name, page);
  }, [name, pathname, page]);
  return <BrowserTitleContext.Provider value={setObject}>{children}</BrowserTitleContext.Provider>;
}

/** Pages contribute only data already loaded for the current object. */
export function useBrowserTitleObject(name: string | null) {
  const setObject = useContext(BrowserTitleContext);
  const { pathname } = useLocation();
  useLayoutEffect(() => {
    setObject?.({ pathname, name });
    return () => setObject?.({ pathname, name: null });
  }, [name, pathname, setObject]);
}

export function useBrowserTitle(page: string, object: string | null = null) {
  useLayoutEffect(() => {
    document.title = composeBrowserTitle(object, page);
  }, [object, page]);
}
