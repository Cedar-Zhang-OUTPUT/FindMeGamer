import {expect,it} from 'vitest';
import {scopedSelection} from '../src/renderer/components/SelectionActions';
it('retains outside selection and adds only explicit scope',()=>expect(scopedSelection(['outside','a'],['a','b'],true)).toEqual(['outside','a','b']));
it('deselects only visible scope',()=>expect(scopedSelection(['outside','a','b'],['a','b'],false)).toEqual(['outside']));
it('rejects the whole addition over limit instead of silently truncating',()=>expect(scopedSelection(['outside'],['a','b'],true,2)).toBeNull());
it('does not mutate selection or auto-select future arrivals',()=>{const selected=['a'];expect(scopedSelection(selected,['a','b'],true)).toEqual(['a','b']);expect(selected).toEqual(['a']);});
