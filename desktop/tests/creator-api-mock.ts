import { vi } from 'vitest';
import type { CreatorAPI } from '../src/shared/creators';
import { creatorFixture,workFixture } from './creator-fixtures';
export function creatorAPIMock():CreatorAPI {
  return {
    list:vi.fn(async()=>({ok:true as const,data:{items:[creatorFixture()],total:1,limit:50,offset:0}})),
    detail:vi.fn(async()=>({ok:true as const,data:creatorFixture()})),
    create:vi.fn(async()=>({ok:true as const,data:creatorFixture()})),
    update:vi.fn(async()=>({ok:true as const,data:creatorFixture()})),
    rebind:vi.fn(async()=>({ok:true as const,data:creatorFixture()})),
    createContact:vi.fn(async()=>({ok:true as const,data:creatorFixture()})),
    updateContact:vi.fn(async()=>({ok:true as const,data:creatorFixture()})),
    works:vi.fn(async()=>({ok:true as const,data:{items:[workFixture()],total:1,limit:50,offset:0}})),
    createWork:vi.fn(async()=>({ok:true as const,data:workFixture()})),
    updateWork:vi.fn(async()=>({ok:true as const,data:workFixture()})),
  };
}
