vi.mock('@/components/ground/ObservatoryGround',()=>({default:()=>null}));
import {renderToStaticMarkup} from 'react-dom/server';
import {StaticRouter} from 'react-router-dom/server';
import {expect,it,vi} from 'vitest';
import {fixtureClimb} from '@/fixtures/data';
import {ClimbPageContent} from './VaultPage';
it('keeps the identity and ledger headings without substitute sentences or unindexed figures',()=>{
 const html=renderToStaticMarkup(<StaticRouter location="/climb/test"><ClimbPageContent data={fixtureClimb} id={fixtureClimb.climb.id}/></StaticRouter>);
 expect(html).toContain('data-climb-identity');
 for(const name of ['Leaderboard','Local Legend','Completions','Positions','Settlements','Registration'])expect(html).toContain(name);
 for(const retired of ['No Leaderboard','Not attached','Canonical registry projection','Vault Balances','Distribution History','Your','data-climb-figure='])expect(html).not.toContain(retired);
});
