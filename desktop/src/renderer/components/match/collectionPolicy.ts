import type {CollectionPlatformState,CollectionSettings} from '../../../shared/settings';
import type {QueryView} from '../../../shared/match';
import {canContinueQuery} from './matchStatus';

/** Administrative policy never replaces a provider's persisted outcome. */
export function collectionLabel(state:CollectionPlatformState):string {
  if(!state.implemented)return 'Real-time data unavailable';
  if(!state.enabled)return 'Collection off';
  return state.credentials_configured?'Access unverified':'Credentials needed';
}
export function eligiblePlatforms(selected:readonly string[],settings:CollectionSettings|null):string[]{
  // Collection controls real-time access, never Library eligibility.
  return selected.filter(platform=>['youtube','x','twitch','instagram'].includes(platform));
}
export function canContinueWithCollection(query:QueryView,settings:CollectionSettings|null):boolean {
  if(!canContinueQuery(query))return false;
  return query.conditions.providers.some(({platform})=>{
    const value=query.sources[platform];
    const source=value&&typeof value==='object'&&!Array.isArray(value)?value:null;
    const library=source?.library;
    if(library&&typeof library==='object'&&!Array.isArray(library)&&['pending','more'].includes(String(library.status)))return true;
    if(!settings?.items.some(item=>item.platform===platform&&item.implemented&&item.enabled&&item.credentials_configured))return false;
    const status=source?.status;
    return !['exhausted','not_supported','budget_exhausted'].includes(String(status));
  });
}
