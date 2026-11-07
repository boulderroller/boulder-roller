import {roomFor,roomDestination,finalsActive,FINALS_PARAM,type WorkshopPage} from './roomRegistry';
export type {WorkshopPage} from './roomRegistry';
export const currentPage = (): WorkshopPage => roomFor(new URLSearchParams(location.search).get('surface')).id;
type Snapshot = { href: string; state: unknown };
const snapshots = new Map<WorkshopPage, Snapshot>();
const key = (page: WorkshopPage) => `br-workshop-page-v1:${page}`;
export function savedWorkshop(page: WorkshopPage): Snapshot | null {
 try { return snapshots.get(page) ?? JSON.parse(sessionStorage.getItem(key(page)) ?? 'null'); } catch { return null; }
}
export function visitWorkshop(page: WorkshopPage, href?: string) {
 const previous = currentPage(), snapshot = { href: location.href, state: history.state };
 snapshots.set(previous, snapshot);
 try { sessionStorage.setItem(key(previous), JSON.stringify(snapshot)); } catch { /* In-memory navigation remains available. */ }
 const finals = finalsActive(location.search), saved = finals ? null : savedWorkshop(page), destination = new URL(href ?? saved?.href ?? roomDestination(page), location.origin);
 destination.searchParams.set('surface', page);
 if (finals) destination.searchParams.set(FINALS_PARAM, '1');
 history.pushState(href ? {} : saved?.state ?? {}, '', destination);
 window.dispatchEvent(new PopStateEvent('popstate'));
}
