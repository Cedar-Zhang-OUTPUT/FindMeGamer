import type { Result } from './bridge';
import type { JsonObject } from './library';

/** Existing v2 contract DTOs, deliberately keeping backend snake_case. */
export type CreatorPlatform = 'youtube' | 'x' | 'twitch' | 'instagram';
export const CREATOR_PLATFORMS: CreatorPlatform[] = ['youtube', 'x', 'twitch', 'instagram'];
export interface OtherContact { label: string | null; value: string; url: string | null }
export interface CreatorFields {
  name: string | null; public_name: string | null; public_name_confirmed: boolean;
  handle: string | null; profile_url: string | null; avatar_url: string | null;
  description: string | null; follower_count: number | null; follower_count_collected_at: string | null;
  languages: string[]; country_code: string | null; country_name: string | null;
  other_contacts: OtherContact[]; source_notes: string | null; internal_notes: string | null; interest_notes: string | null;
}
export type CreatorField = keyof CreatorFields;
export const CREATOR_FIELDS: CreatorField[] = ['name','public_name','public_name_confirmed','handle','profile_url','avatar_url','description','follower_count','follower_count_collected_at','languages','country_code','country_name','other_contacts','source_notes','internal_notes','interest_notes'];
export interface CreatorIdentity { platform: CreatorPlatform; account_id: string | null; canonical_url: string | null; revision: number }
export interface ContactFields { email: string; purpose: string | null; source_url: string | null; is_active: boolean; verification_notes: string | null }
export type ContactField = keyof ContactFields;
export const CONTACT_FIELDS: ContactField[] = ['email','purpose','source_url','is_active','verification_notes'];
export interface ContactDetail extends ContactFields {
  id: string; origin: 'manual' | 'source'; source_type: string; validation_state: string;
  source_fields: JsonObject; manual_overrides: JsonObject; identity_revision: number; is_current_identity: boolean; updated_at: string;
}
export interface CreatorDetail extends CreatorFields {
  id: string; platform: CreatorPlatform; revision: number; favorite: boolean;
  source_identity: CreatorIdentity; source_fields: CreatorFields; manual_overrides: JsonObject;
  overridden_fields: CreatorField[]; contacts: ContactDetail[]; work_count: number;
  last_analyzed_at: string | null; next_analysis_at: string | null; analysis_available: boolean;
}
export interface CreatorPage { items: CreatorDetail[]; total: number; limit: number; offset: number }
export interface CreatorListInput { query?: string; platform?: CreatorPlatform; language?: string; onlyCollection?: boolean; limit?: number; offset?: number }
export type CreatorCreate = Partial<CreatorFields> & { platform?: CreatorPlatform; account_id?: string | null; favorite?: boolean };
export type CreatorPatch = Partial<CreatorFields> & { favorite?: boolean; expected_revision: number; reset_fields?: CreatorField[] };
export interface IdentityUpdate { platform: CreatorPlatform; account_id?: string | null; profile_url?: string | null; confirmed: true; expected_revision: number }
export type ContactCreate = Pick<ContactFields,'email'> & Partial<Omit<ContactFields,'email'>> & { expected_revision: number };
export type ContactPatch = Partial<ContactFields> & { expected_revision: number; reset_fields?: ContactField[] };
export type WorkContentType = 'unverified' | 'gameplay' | 'livestream' | 'review' | 'commentary' | 'trailer' | 'news' | 'other';
export interface WorkMetric { name: string; value: number }
export interface WorkFields {
  platform: CreatorPlatform | null; work_name: string | null; content_title: string | null;
  content_type: WorkContentType; source_url: string | null; content_id: string | null;
  published_at: string | null; collected_at: string | null; metrics: WorkMetric[]; game_id: string | null;
  verification_notes: string | null; evidence_excerpt: string | null; timestamp_seconds: number | null;
}
export type WorkField = keyof WorkFields;
export const WORK_FIELDS: WorkField[] = ['platform','work_name','content_title','content_type','source_url','content_id','published_at','collected_at','metrics','game_id','verification_notes','evidence_excerpt','timestamp_seconds'];
export interface WorkDetail extends WorkFields {
  id: string; creator_id: string; platform: CreatorPlatform; source_platform: CreatorPlatform;
  origin: 'manual' | 'source'; revision: number; identity_revision: number; is_current_identity: boolean;
  source_content_id: string | null; source_collected_at: string | null; source_fields: JsonObject; manual_overrides: JsonObject;
}
export type WorkCreate = Partial<WorkFields> & { expected_identity_revision: number };
export type WorkPatch = Partial<WorkFields> & { expected_revision: number; reset_fields?: WorkField[] };
export interface WorkPage { items: WorkDetail[]; total: number; limit: number; offset: number }
export interface WorkListInput { creatorId: string; includePreviousIdentity?: boolean; limit?: number; offset?: number }
export interface CreatorAPI {
  list(input: CreatorListInput): Promise<Result<CreatorPage>>;
  detail(id: string): Promise<Result<CreatorDetail>>;
  create(input: { data: CreatorCreate; idempotencyKey: string }): Promise<Result<CreatorDetail>>;
  update(input: { id: string; data: CreatorPatch }): Promise<Result<CreatorDetail>>;
  rebind(input: { id: string; data: IdentityUpdate }): Promise<Result<CreatorDetail>>;
  createContact(input: { creatorId: string; data: ContactCreate; idempotencyKey: string }): Promise<Result<CreatorDetail>>;
  updateContact(input: { creatorId: string; contactId: string; data: ContactPatch }): Promise<Result<CreatorDetail>>;
  works(input: WorkListInput): Promise<Result<WorkPage>>;
  createWork(input: { creatorId: string; data: WorkCreate; idempotencyKey: string }): Promise<Result<WorkDetail>>;
  updateWork(input: { creatorId: string; workId: string; data: WorkPatch }): Promise<Result<WorkDetail>>;
}
