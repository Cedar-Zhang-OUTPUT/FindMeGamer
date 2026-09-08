import type { SavedSetCreate, SavedSetView } from '../src/shared/savedSets';
import { ACTIVITY_ID, CANDIDATE_ID, MATCH_TIME, QUERY_ID } from './match-fixtures';

export const SET_ID = '3456789a-3456-4456-8456-3456789abcde';
export const REQUEST_ID = '456789ab-4567-4567-8567-456789abcdef';
export const SECOND_CANDIDATE_ID = '56789abc-5678-4678-8678-56789abcdef0';
export const SET_KEY = 'saved-set-request-1';
export function savedSetCreateFixture(): SavedSetCreate {
  return { request_id: REQUEST_ID, name: '  Launch shortlist  ', candidate_ids: [SECOND_CANDIDATE_ID, CANDIDATE_ID, SECOND_CANDIDATE_ID.toUpperCase()] };
}
export function savedSetFixture(): SavedSetView {
  return { id: SET_ID, query_id: QUERY_ID, activity_id: ACTIVITY_ID, name: 'Launch shortlist',
    candidate_ids: [SECOND_CANDIDATE_ID, CANDIDATE_ID], count: 2, created_at: MATCH_TIME };
}
