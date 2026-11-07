import {FeedV13} from './FeedV13';
import { useEffect, useState } from 'react';
import {FeedV4} from './FeedV4';
import {FeedV9} from './FeedV9';
import {FeedV11} from './FeedV11';
import {FeedV12} from './FeedV12';
import {FeedV8} from './FeedV8';
import {FeedV7} from './FeedV7';
import {feedV7ById,parseFeedV7} from './feedV7Model';
import {FeedV6} from './FeedV6';
import {parseFeedV6,withV6Example,feedV6ById} from './feedV6Model';
import {FeedV5} from './FeedV5';
import {parseFeedV5,withV5Example,feedV5ById} from './feedV5Model';
import {parseFeedV4} from './feedV4Model';
import { FeedV3 } from './FeedV3';
import { parseFeedV3 } from './feedV3Model';
import { FeedV2 } from './FeedV2';
import { parseFeedV2 } from './feedV2Model';
import { FeedV1 } from './FeedV1';
import { feedById, type FeedScenario } from './feedModel';
export type FeedSettings = {
    active?: boolean;
    variant?: 'feed-v1' | 'feed-v2' | 'feed-v3' | 'feed-v4' | 'feed-v5' | 'feed-v6' | 'feed-v7' | 'feed-v8' | 'feed-v9' | 'feed-v11' | 'feed-v12' | 'feed-v13';
    riderId?:string|null;
    scenario: FeedScenario;
    filter: string;
    state: 'ready' | 'loading' | 'empty' | 'error';
};
export function FeedPreview() {
    const [revision, setRevision] = useState(0);
    const [received, setReceived] = useState(window.parent === window);
    const [settings, setSettings] = useState<FeedSettings>(() => ({ riderId:new URLSearchParams(location.search).get('rider'), scenario: ['feed-v7','feed-v8','feed-v9','feed-v11','feed-v12','feed-v13'].includes(new URLSearchParams(location.search).get('variant')??'')?feedV7ById(new URLSearchParams(location.search).get('scenario')):new URLSearchParams(location.search).get('variant') === 'feed-v6' ? withV6Example(feedV6ById(new URLSearchParams(location.search).get('scenario'))) : new URLSearchParams(location.search).get('variant') === 'feed-v5' ? withV5Example(feedV5ById(new URLSearchParams(location.search).get('scenario'))) : feedById(new URLSearchParams(location.search).get('scenario')), filter: ['feed-v5','feed-v6','feed-v7','feed-v8','feed-v9','feed-v11','feed-v12','feed-v13'].includes(new URLSearchParams(location.search).get('variant')??'')&&new URLSearchParams(location.search).get('filter')==='following'?'following':'everyone', state: 'ready', variant: new URLSearchParams(location.search).get('variant') === 'feed-v13' ? 'feed-v13' : new URLSearchParams(location.search).get('variant') === 'feed-v12' ? 'feed-v12' : new URLSearchParams(location.search).get('variant') === 'feed-v11' ? 'feed-v11' : new URLSearchParams(location.search).get('variant') === 'feed-v9' ? 'feed-v9' : new URLSearchParams(location.search).get('variant') === 'feed-v8' ? 'feed-v8' : new URLSearchParams(location.search).get('variant') === 'feed-v7' ? 'feed-v7' : new URLSearchParams(location.search).get('variant') === 'feed-v6' ? 'feed-v6' : new URLSearchParams(location.search).get('variant') === 'feed-v5' ? 'feed-v5' : new URLSearchParams(location.search).get('variant') === 'feed-v4' ? 'feed-v4' : new URLSearchParams(location.search).get('variant') === 'feed-v3' ? 'feed-v3' : new URLSearchParams(location.search).get('variant') === 'feed-v2' ? 'feed-v2' : 'feed-v1' }));
    useEffect(() => { const receive = (event: MessageEvent) => { if (event.origin !== location.origin || event.source !== window.parent || event.data?.type !== 'feed-settings')
        return; const next = event.data.settings; try {
        const parsed = next.scenario ? (['feed-v7','feed-v8','feed-v9','feed-v11','feed-v12','feed-v13'].includes(next.variant) ? parseFeedV7(next.scenario) : next.variant === 'feed-v6' ? parseFeedV6(next.scenario) : next.variant === 'feed-v5' ? parseFeedV5(next.scenario) : next.variant === 'feed-v4' ? parseFeedV4(next.scenario) : next.variant === 'feed-v3' ? parseFeedV3(next.scenario) : parseFeedV2(next.scenario)) : null;
        setReceived(true);
        if (parsed) setRevision(v => v + 1);
        setSettings(previous => ({ ...previous, ...next, scenario: parsed ?? previous.scenario }));
    }
    catch { } }; window.addEventListener('message', receive); window.parent.postMessage({ type: 'feed-ready' }, location.origin); return () => window.removeEventListener('message', receive); }, []);
    useEffect(()=>{if(window.parent!==window||!['feed-v5','feed-v6','feed-v7','feed-v8','feed-v9','feed-v11','feed-v12','feed-v13'].includes(settings.variant??''))return;const open=(e:MessageEvent)=>{if(e.origin===location.origin&&e.source===window&&e.data?.type==='feed-open-ride')location.assign(e.data.href);};window.addEventListener('message',open);return()=>window.removeEventListener('message',open);},[settings.variant]);
    const send = (type: string, extra: {filter?:string;riderId?:string|null} = {}) => {if(window.parent===window&&['feed-v5','feed-v6','feed-v7','feed-v8','feed-v9','feed-v11','feed-v12','feed-v13'].includes(settings.variant??'')){setSettings(s=>({...s,riderId:'riderId' in extra?extra.riderId:s.riderId,filter:extra.filter??s.filter,state:type==='feed-recover'?'ready':s.state}));}else window.parent.postMessage({ type, ...extra }, location.origin);};
    if (!received)
        return <div className="f1-page"/>;
    const Candidate = settings.variant === 'feed-v13' ? FeedV13 : settings.variant === 'feed-v12' ? FeedV12 : settings.variant === 'feed-v11' ? FeedV11 : settings.variant === 'feed-v9' ? FeedV9 : settings.variant === 'feed-v8' ? FeedV8 : settings.variant === 'feed-v7' ? FeedV7 : settings.variant === 'feed-v6' ? FeedV6 : settings.variant === 'feed-v5' ? FeedV5 : settings.variant === 'feed-v4' ? FeedV4 : settings.variant === 'feed-v3' ? FeedV3 : settings.variant === 'feed-v2' ? FeedV2 : FeedV1;
    return <Candidate key={`${settings.variant}:${revision}`} {...settings} onFilter={filter => send('feed-filter', { filter })} onRecover={() => send('feed-recover')} onRider={riderId=>send('feed-rider',{riderId})}/>;
}
