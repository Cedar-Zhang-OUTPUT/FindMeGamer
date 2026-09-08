import type {CollectionPlatformState,CollectionSettings} from '../../../shared/settings';
import type {QueryView} from '../../../shared/match';
import {canContinueQuery} from './matchStatus';

/** Administrative policy never replaces a provider's persisted outcome. */
export function collectionLabel(state:CollectionPlatformState):string {
  if(!state.implemented||!['youtube','x'].includes(state.platform))return 'Unavailable in this version';
  if(!state.enabled)return 'Collection off';
  return state.credentials_configured?'Access unverified':'Credentials needed';
}
export function eligiblePlatforms(selected:readonly string[],settings:CollectionSettings|null):string[]{
  return selected.filter(platform=>['youtube','x'].includes(platform)&&settings?.items.some(item=>item.platform===platform&&item.implemented&&item.enabled&&item.credentials_configured));
}
export function canContinueWithCollection(query:QueryView,settings:CollectionSettings|null):boolean {
  if(!canContinueQuery(query))return false;
  return eligiblePlatforms(query.conditions.providers.map(provider=>provider.platform),settings).some(platform=>{
    const value=query.sources[platform];
    const status=value&&typeof value==='object'&&!Array.isArray(value)?value.status:null;
    return !['exhausted','not_supported','budget_exhausted'].includes(String(status));
  });
}
