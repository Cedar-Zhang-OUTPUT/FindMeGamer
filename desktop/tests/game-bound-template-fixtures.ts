import type {BuiltinTemplate,TemplateVersion} from '../src/shared/drafts';
import {fixed} from '../src/main/drafts-validation';
import {draftIds} from './drafts-fixtures';
const subject='Try Fixture Game',fixed_fragments=['<p>Hi ',',</p><p>I noticed ',', including ','. ','</p><p>Fixture Game is a gardening adventure.</p><p>https://example.test/game</p>'];
export const gameBoundBuiltin:BuiltinTemplate={name:'Fixture Game',subject,fixed_fragments,fixed_hash:fixed(subject,fixed_fragments,'response'),key:'game-outreach-v1',requires_explicit_registration:true,source_metadata:{kind:'game_bound',document_id:null,raw_hash:null,revision:1,game_id:draftIds.game,game_revision:3,game_fingerprint:'a'.repeat(64),steam_app_id:null,sender_name:null}};
export const gameBoundVersion:TemplateVersion={name:gameBoundBuiltin.name,subject,fixed_fragments,fixed_hash:gameBoundBuiltin.fixed_hash,source_metadata:gameBoundBuiltin.source_metadata,id:draftIds.template,game_id:draftIds.game,created_at:'2026-09-09T00:00:00Z'};
