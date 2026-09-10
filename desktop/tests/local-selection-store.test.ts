import {mkdtemp,readFile,readdir,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {afterEach,expect,it} from 'vitest';
import {LocalSelectionStore} from '../src/main/local-selection-store';
import {emptySelectionDraft,mergeSelectionRead} from '../src/renderer/components/match/localSelectionPrepare';
import {preparationFixture} from './outreach-fixtures';
const directories:string[]=[];afterEach(async()=>{for(const directory of directories.splice(0))await rm(directory,{recursive:true,force:true});});
it('persists across restart while isolating service, credentials, activity and query',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'fmg-local-selection-test-'));directories.push(dir);
 let connection={serviceUrl:'https://workspace.example.test',key:'synthetic-only-key'};
 const store=new LocalSelectionStore(dir,async()=>connection),p=preparationFixture(),context={activityId:p.activity_id,queryId:'11111111-1111-4111-8111-111111111111'};
 const opened=await store.read(context);if(!opened.ok)throw Error('read');const state={stage:'ready' as const,draft:mergeSelectionRead(emptySelectionDraft(opened.data.scope,p.activity_id),[p])};
 expect(await store.write({...context,scope:opened.data.scope,state})).toEqual({ok:true,data:undefined});
 expect(await new LocalSelectionStore(dir,async()=>connection).read(context)).toEqual({ok:true,data:{scope:opened.data.scope,state}});
 for(const other of [{...context,queryId:'22222222-2222-4222-8222-222222222222'},{...context,activityId:'33333333-3333-4333-8333-333333333333'}])expect(await store.read(other)).toEqual({ok:true,data:{scope:opened.data.scope,state:null}});
 connection={...connection,key:'different-key'};expect((await store.read(context))).not.toEqual(opened);expect(await store.write({...context,scope:opened.data.scope,state})).toMatchObject({ok:false,error:{code:'connection_changed'}});
 connection={...connection,serviceUrl:'https://other.example.test'};expect(await store.read(context)).toMatchObject({ok:true,data:{state:null}});
 const files=await readdir(join(dir,'selection-drafts',opened.data.scope));expect(files).toHaveLength(1);expect(await readFile(join(dir,'selection-drafts',opened.data.scope,files[0]),'utf8')).not.toContain('synthetic-only-key');
});
it('rejects path traversal and cross-activity journals',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'fmg-local-selection-test-'));directories.push(dir);const store=new LocalSelectionStore(dir,async()=>({serviceUrl:'https://example.test',key:'synthetic'}));
 expect(await store.read({activityId:'../../outside',queryId:null})).toMatchObject({ok:false});
 const context={activityId:preparationFixture().activity_id,queryId:null};const result=await store.read(context);if(!result.ok)throw Error('read');
 expect(await store.write({...context,scope:result.data.scope,state:{stage:'ready',draft:emptySelectionDraft(result.data.scope,'another')}})).toMatchObject({ok:false});
});
