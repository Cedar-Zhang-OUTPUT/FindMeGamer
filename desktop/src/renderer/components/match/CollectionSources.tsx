import type {QueryView} from '../../../shared/match';
import {ErrorNotice} from '../Primitives';
import {canContinueQuery,taskLabel} from './matchStatus';
import {queryIsRunning} from './useMatchSession';
import {canContinueWithCollection,collectionLabel,eligiblePlatforms} from './collectionPolicy';
import type {useCollectionPolicy} from './useCollectionPolicy';

export function CollectionSources({selected,query,policy,onSettings}:{selected:readonly string[];query?:QueryView|null;policy:ReturnType<typeof useCollectionPolicy>;onSettings?:()=>void}){
  const running=queryIsRunning(query??null);
  const unavailable=policy.phase==='ready'&&(!query?eligiblePlatforms(selected,policy.data).length===0:
    query.status!=='completed'&&!running&&(eligiblePlatforms(selected,policy.data).length===0||(canContinueQuery(query)&&!canContinueWithCollection(query,policy.data))));
  return <section className="match-collection" aria-label="Collection sources">
    <div className="match-source-states">{selected.map(platform=>{
      const value=query?.sources[platform],source=value&&typeof value==='object'&&!Array.isArray(value)?value:null;
      const saved=policy.data?.items.find(item=>item.platform===platform);
      const title=platform==='youtube'?'YouTube':platform==='x'?'X':taskLabel(platform);
      const off=Boolean(saved?.implemented&&!saved.enabled);
      const resumed=source?.blocked_reason==='collection_disabled'&&saved?.enabled&&saved.implemented&&saved.credentials_configured;
      return <div key={platform} className={`match-source-status ${off?'collection-off':''}`}>
        <strong>{source?`${title} · ${taskLabel(typeof source.status==='string'?source.status:'unknown')}`:title}</strong>
        <span>{off&&running&&source?.blocked_reason!=='collection_disabled'&&source?.status!=='exhausted'?'Pauses after in-flight collection':resumed?'Ready to continue':saved?collectionLabel(saved):source?.blocked_reason==='collection_disabled'?'Collection off':'Checking collection settings…'}</span>
      </div>;
    })}</div>
    <div className="match-collection-actions">{unavailable&&<strong role="status">No available sources</strong>}{policy.phase==='failed'&&<span>Showing last known settings</span>}{onSettings&&<button className="text-button" onClick={onSettings}>Collection settings</button>}</div>
    {policy.error&&<ErrorNotice error={policy.error} onRetry={policy.refresh}/>}
  </section>;
}
