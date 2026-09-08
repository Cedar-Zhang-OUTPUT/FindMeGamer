import {vi} from 'vitest';
import type {OutreachAPI} from '../src/shared/outreach';
export function outreachAPIMock():OutreachAPI{return {
  selections:vi.fn(async()=>({ok:true as const,data:{items:[],total:0,offset:0,limit:200}})),
  selection:vi.fn(),add:vi.fn(),bulk:vi.fn(),update:vi.fn(),cancel:vi.fn(),
  batches:vi.fn(async()=>({ok:true as const,data:{items:[],total:0,offset:0,limit:50}})),batch:vi.fn(),freeze:vi.fn(),
};}
