import { ChevronRight } from 'lucide-react';
import { PortalFrame, PortalPage } from '../components/portal/PortalSpine';

/*
 * Guide — the docs' contents page (Tim-ratified 2026-09-03, board "Guide and
 * Search" on the Night Ledger Rooms canvas).
 *
 * The public docs are the ratified prose, so this page stops describing them:
 * six sheets in the docs' own sections, each row a page title that opens the
 * page. Nothing here is copy; the titles are the docs site's.
 */

const DOCS_ORIGIN = 'https://docs.boulderroller.xyz';

const SECTIONS: Array<{ id: string; title: string; pages: Array<[string, string]> }> = [
  {
    id: 'get-started',
    title: 'Get started',
    pages: [
      ['Access', '/getting-started/access'],
      ['Create an account', '/getting-started/account'],
      ['Upload a ride', '/getting-started/upload'],
      ['iOS app', '/getting-started/ios'],
    ],
  },
  {
    id: 'rides',
    title: 'Rides',
    pages: [
      ['What happens to a ride', '/rides/processing'],
      ['Results', '/rides/results'],
      ['CAL', '/rides/cal'],
      ['Training', '/rides/training'],
      ['Feed and following', '/rides/feed'],
      ['Privacy and your data', '/rides/privacy'],
    ],
  },
  {
    id: 'climbs',
    title: 'Climbs',
    pages: [
      ['Climbs', '/climbs/climbs'],
      ['Leaderboards', '/climbs/leaderboards'],
      ['Local Legend', '/climbs/local-legend'],
      ['Vaults', '/climbs/vaults'],
    ],
  },
  {
    id: 'dung',
    title: 'DUNG',
    pages: [
      ['Settlement weeks', '/dung/settlement-weeks'],
      ['Distribution', '/dung/distribution'],
      ['Balance and wallet', '/dung/balance'],
      ['Fees and minimums', '/dung/fees'],
    ],
  },
  {
    id: 'reference',
    title: 'Reference',
    pages: [
      ['Glossary', '/reference/glossary'],
      ['FAQ', '/reference/faq'],
    ],
  },
  {
    id: 'support',
    title: 'Support',
    pages: [
      ['Common issues', '/support/common-issues'],
      ['Contact', '/support/contact'],
    ],
  },
];

function GuideSheet({ id, title, pages }: (typeof SECTIONS)[number]) {
  const headingId = `guide-${id}-heading`;
  return (
    <section className="guide-sheet" aria-labelledby={headingId}>
      <h2 id={headingId} className="guide-sheet__eyebrow">{title}</h2>
      {pages.map(([label, path]) => (
        <a
          key={path}
          className="guide-row"
          href={`${DOCS_ORIGIN}${path}`}
          target="_blank"
          rel="noopener noreferrer"
        >
          <span className="guide-row__label">{label}</span>
          <ChevronRight size={14} aria-hidden="true" className="guide-row__chevron" />
        </a>
      ))}
    </section>
  );
}

export default function Docs() {
  return (
    <PortalPage className="docs-page">
      <PortalFrame>
        <div className="guide">
          <div className="guide__header">
            <h1 className="guide__title">Guide</h1>
            <a className="guide__word" href={`${DOCS_ORIGIN}/`} target="_blank" rel="noopener noreferrer">
              Public docs
            </a>
          </div>
          <div className="guide__grid">
            <div className="guide__column">
              {SECTIONS.slice(0, 2).map((section) => <GuideSheet key={section.id} {...section} />)}
            </div>
            <div className="guide__column">
              {SECTIONS.slice(2).map((section) => <GuideSheet key={section.id} {...section} />)}
            </div>
          </div>
        </div>
      </PortalFrame>
    </PortalPage>
  );
}
