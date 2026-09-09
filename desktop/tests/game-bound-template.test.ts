import {it,expect} from 'vitest';
import {decodeCatalog,decodeTemplate,fixed} from '../src/main/drafts-validation';
import {draftIds,templateVersion} from './drafts-fixtures';
const subject='Try Garden Story',fragments=['<p>Hi ',', ',' — ','. ','</p><p>Garden Story. A gardening game.</p>'];
const builtin={name:'Garden Story',subject,fixed_fragments:fragments,fixed_hash:fixed(subject,fragments,'response'),key:'game-outreach-v1',requires_explicit_registration:true,source_metadata:{kind:'game_bound',document_id:null,raw_hash:null,revision:1,game_id:draftIds.game,game_revision:3,game_fingerprint:'a'.repeat(64),steam_app_id:null,sender_name:null}};
it('decodes game-bound content and historical versions without weakening hash or game scope',()=>{
 const version={...builtin,id:draftIds.template,game_id:draftIds.game,created_at:templateVersion.created_at};delete (version as any).key;delete (version as any).requires_explicit_registration;
 expect(decodeCatalog({items:[version],builtin},draftIds.game).builtin.fixed_hash).toBe(builtin.fixed_hash);
 for(const change of [{game_id:draftIds.activity},{game_revision:-1},{game_fingerprint:'invalid'}])expect(()=>decodeCatalog({items:[],builtin:{...builtin,source_metadata:{...builtin.source_metadata,...change}}},draftIds.game)).toThrow();
 expect(()=>decodeCatalog({items:[],builtin:{...builtin,fixed_hash:'b'.repeat(64)}},draftIds.game)).toThrow();
 expect(decodeTemplate({...templateVersion,source_metadata:{...templateVersion.source_metadata,game_id:null,game_revision:null,game_fingerprint:null,sender_name:null}}).id).toBe(draftIds.template);
});
