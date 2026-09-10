import { readFileSync } from 'node:fs';
import { expect, it, vi } from 'vitest';
import { authenticatedGameRequest } from '../src/main/transport';
import { authenticatedAnalysisRequest } from '../src/main/analyze-transport';
import { authenticatedDraftsRequest } from '../src/main/drafts-transport';
const id='11111111-1111-4111-8111-111111111111';
const connection={serviceUrl:'https://workspace.example',key:'synthetic'};
it('opts in at Game, import/analysis and nested draft response boundaries', async()=>{
  const fetcher=vi.fn(async()=>Response.json({}));
  await authenticatedGameRequest(fetcher,connection,{method:'GET',path:`/api/v2/library/games/${id}`});
  await authenticatedAnalysisRequest(fetcher,connection,{method:'POST',path:'/api/v1/jobs/analysis',body:{target_type:'game',url:'https://store.steampowered.com/app/12345/',mode:'reanalyze'},idempotencyKey:'synthetic'});
  await authenticatedDraftsRequest(fetcher,connection,{method:'GET',path:`/api/v2/outreach/compositions/${id}`});
  for(const [,init] of fetcher.mock.calls as unknown as [string,RequestInit][]){expect(new Headers(init.headers).get('X-FMG-Steam-References')).toBe('1');expect(init.redirect).toBe('error');}
});
it('wires the opt-in only into authenticated API transports',()=>{
  for(const name of ['transport','analyze-transport','creator-transport','saved-set-transport','settings-transport','collaboration-transport','sending-transport','drafts-transport','match-transport','outreach-transport']){
    const source=readFileSync(new URL(`../src/main/${name}.ts`,import.meta.url),'utf8');expect(source).toContain('...STEAM_REFERENCES_OPT_IN');
  }
});
