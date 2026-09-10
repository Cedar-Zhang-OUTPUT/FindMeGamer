import type {Result} from './bridge';
import type {LocalPrepareState} from '../renderer/components/match/localSelectionPrepare';
export interface LocalSelectionContext {activityId:string;queryId:string|null}
export interface LocalSelectionsAPI {
  read(input:LocalSelectionContext):Promise<Result<{scope:string;state:LocalPrepareState|null}>>;
  write(input:LocalSelectionContext&{scope:string;state:LocalPrepareState}):Promise<Result<void>>;
}
