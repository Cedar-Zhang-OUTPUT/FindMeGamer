import {readFileSync} from 'node:fs';
import {expect,it} from 'vitest';
import {decodeCandidate,decodeCreatorSearch,decodeCreatorSearchPerson,decodeEvaluationResult,decodePage} from '../src/main/match-validation';

// Opt-in, read-only integration evidence; never starts a search or contacts a server.
const fixturePath=process.env.FMG_CREATOR_SEARCH_DTO;
it.skipIf(!fixturePath)('accepts actual isolated FastAPI task, unit, history and result DTOs without projections',()=>{
  const bundle=JSON.parse(readFileSync(fixturePath!,'utf8'));
  for(const key of ['queued','partial','completed'])expect(decodeCreatorSearch(bundle[key])).toEqual(bundle[key]);
  for(const key of ['partial_creators','creators'])expect(decodePage(bundle[key],decodeCreatorSearchPerson,100,item=>item.candidate_id)).toEqual(bundle[key]);
  expect(decodePage(bundle.history,item=>decodeCreatorSearch(item),100,item=>item.id)).toEqual(bundle.history);
  expect(decodePage(bundle.results,decodeEvaluationResult,100,item=>item.candidate_id)).toEqual(bundle.results);
  expect(decodePage(bundle.candidates,decodeCandidate,100,item=>item.id)).toEqual(bundle.candidates);
  expect(bundle.partial.status).toBe('partial');
  expect(bundle.completed.status).toBe('completed');
});
