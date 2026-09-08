import {expect,it} from 'vitest';
import {newTemplateFragments,templatePreviewHTML,SLOT_KEYS} from '../src/renderer/components/match/templateText';
it('converts only new user-authored text into five escaped fragments in the four-slot order',()=>{
  const body='Hi {{firstName}},\n{{channelName}} & {{reference}}: {{observation}}\n<script>no</script>';
  expect(newTemplateFragments(body)).toEqual(['<p>Hi ',',<br>',' &amp; ',': ','<br>&lt;script&gt;no&lt;/script&gt;</p>']);
});
it('rejects missing, duplicated, reordered or unknown personalization markers',()=>{
  const valid=SLOT_KEYS.map(key=>`{{${key}}}`).join(' ');
  for(const body of ['',valid.replace('{{reference}}',''),valid+'{{firstName}}',valid.replace('{{firstName}}','{{channelName}}'),valid+'{{game}}'])expect(()=>newTemplateFragments(body)).toThrow();
});
it('does not rewrite existing fixed fragments when assembling a read-only preview',()=>{
  const fragments=['<p><b>Hi </b>',',</p><p>',' enjoyed <b>','</b>. ','</p><p>Original signature</p>'];
  const template={fixed_fragments:fragments};const before=JSON.stringify(template);
  const html=templatePreviewHTML(template,{firstName:'A & B',channelName:'Channel',reference:'[Full Playthrough]',observation:'Made a point.'});
  expect(html).toContain('<p><b>Hi </b>');expect(html).toContain('A &amp; B');expect(html).toContain('[Full Playthrough]');expect(html).toContain('</p><p>Original signature</p>');expect(JSON.stringify(template)).toBe(before);
});
