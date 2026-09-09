import {test} from '@playwright/test';
import {analyzeFixture,requireCheck,canonical,events,eventCounts} from './analyze-fixture';
test.use({trace:'off',screenshot:'off',video:'off'});
test('Analyze production clients decode existing isolated profiles, jobs and mixed cursor history without writes',async()=>{
 test.skip(process.env.FMG_ANALYZE_FROZEN!=='64692'||process.env.FMG_ANALYZE_API!=='approved','Root requires exclusive64692 lease and frozen source/build.');test.setTimeout(90_000);
 const f=await analyzeFixture('api'),offset=(await events()).length;
 try{
  await f.checkpoint('saved_profiles');const game=await f.games.detail(f.ids.game_id),yt=await f.creators.detail(f.ids.youtube_id),x=await f.creators.detail(f.ids.x_id);
  requireCheck(game.id===f.ids.game_id&&game.reference_works.length>0&&Object.keys(game.manual_overrides).length>0,'game_preserved_fixture');
  requireCheck(yt.source_identity.account_id==='UCanalyzeFixture01'&&yt.analysis_available&&yt.brief,'youtube_bound_analysis');
  requireCheck(x.source_identity.canonical_url==='https://x.com/i/user/900000001'&&x.analysis_available&&x.analysis&&x.source_status,'x_bound_analysis');
  await f.checkpoint('saved_jobs_and_history');let failed=0,succeeded=0;for(const jobId of f.ids.jobs){const job=await f.analysis.detail({jobId});if(job.status==='failed')failed++;if(job.status==='succeeded')succeeded++;}requireCheck(failed>=1&&succeeded>=1,'historical_failure_and_success');
  let cursor:string|undefined,seen=new Set<string>(),pages=0,more=true;while(more&&pages++<20){const page=await f.analysis.changed({...(cursor?{cursor}:{}),limit:20});for(const row of page.items){requireCheck(!seen.has(row.resource_id),'duplicate_cursor_item');seen.add(row.resource_id);}requireCheck(!page.has_more||page.cursor!==cursor,'cursor_did_not_advance');cursor=page.cursor;more=page.has_more;}requireCheck(!more,'history_page_bound');
  const works=await f.creators.works({creatorId:yt.id,limit:50,offset:0});requireCheck(works.total===11,'youtube_source_work_count');
  requireCheck(canonical(await eventCounts(offset))===canonical({})&&f.writes.length===0,'readonly_no_upstream_effects');Object.assign(f.report,{status:'passed',stage:'complete',checks:['existing_same_uuid_profiles','bound_youtube_and_numeric_x','historical_failed_and_succeeded_jobs','opaque_cursor_history','source_works'],historical_jobs:{failed,succeeded},history_items:seen.size,first_binding:'not_repeated',response_or_smtp_writes:0});
 }catch(e){f.report.status='failed';f.report.error=e instanceof Error&&/^[a-z0-9_]+$/.test(e.message)?e.message:'adapter_assertion_failed';}finally{await f.finish();}
 requireCheck(f.report.status==='passed','analyze_api_failed');
});
