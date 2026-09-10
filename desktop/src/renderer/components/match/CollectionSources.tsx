import type {QueryView} from '../../../shared/match';
import {ErrorNotice} from '../Primitives';
import {canContinueQuery,taskLabel} from './matchStatus';
import {queryIsRunning} from './useMatchSession';
import {canContinueWithCollection,collectionLabel,eligiblePlatforms} from './collectionPolicy';
import type {useCollectionPolicy} from './useCollectionPolicy';

export function CollectionSources({selected,query,policy,onSettings,showError=true}:{selected:readonly string[];query?:QueryView|null;policy:ReturnType<typeof useCollectionPolicy>;onSettings?:()=>void;showError?:boolean}){
  const running=queryIsRunning(query??null);
  const unavailable=policy.phase==='ready'&&(!query?eligiblePlatforms(selected,policy.data).length===0:
    query.status!=='completed'&&!running&&(eligiblePlatforms(selected,policy.data).length===0||(canContinueQuery(query)&&!canContinueWithCollection(query,policy.data))));
  return <section className="match-collection" aria-label="Collection sources">
    <div className="match-source-states">{selected.map(platform=>{
      const value=query?.sources[platform],source=value&&typeof value==='object'&&!Array.isArray(value)?value:null;
      const saved=policy.data?.items.find(item=>item.platform===platform);
      const title=platform==='youtube'?'YouTube':platform==='x'?'X':taskLabel(platform);
      const off=Boolean(saved?.implemented&&!saved.enabled);
      const library=source?.library&&typeof source.library==='object'&&!Array.isArray(source.library)?source.library:null;
      const realtimeUnavailable=Boolean(saved&&(!saved.implemented||!saved.enabled||!saved.credentials_configured))||['not_supported','missing_connection','failed'].includes(String(source?.status));
      const resumed=source?.blocked_reason==='collection_disabled'&&saved?.enabled&&saved.implemented&&saved.credentials_configured;
      return <div key={platform} className={`match-source-status ${off?'collection-off':''}`}>
        <strong>{source?`${title} · ${taskLabel(typeof source.status==='string'?source.status:'unknown')}`:title}</strong>
        <span>{library?`Library · ${typeof library.added_count==='number'?`${library.added_count} found · `:''}${library.status==='complete'?'Search complete':library.status==='more'?'More available':'Pending'}`:'Library'}</span>
        <span>{off&&running&&source?.blocked_reason!=='collection_disabled'&&source?.status!=='exhausted'?'Pauses after in-flight collection':resumed?'Ready to continue':realtimeUnavailable?'Real-time data unavailable':saved?collectionLabel(saved):'Checking real-time access…'}</span>
        {off&&<span>Real-time collection off</span>}
      </div>;
    })}</div>
    <div className="match-collection-actions">{unavailable&&<strong role="status">No available sources</strong>}{policy.phase==='failed'&&<span>Showing last known settings</span>}{onSettings&&<button className="text-button" onClick={onSettings}>Collection settings</button>}</div>
    {showError&&policy.error&&<ErrorNotice error={policy.error} onRetry={policy.refresh}/>}
  </section>;
}
