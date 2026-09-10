// @vitest-environment jsdom
import {render,fireEvent,cleanup} from '@testing-library/react';
import {afterEach,expect,test,vi} from 'vitest';
import {tableScrollKeys} from '../src/renderer/components/match/tableScrollKeys';
afterEach(cleanup);
function setup(){
 const view=render(<main onKeyDown={tableScrollKeys}><div className="review-table-scroll" tabIndex={0}><button>Row action</button><input aria-label="Field"/></div></main>);
 const main=view.container.querySelector('main')!,region=main.firstElementChild!;
 Object.defineProperties(main,{clientHeight:{value:500},scrollHeight:{value:5000}});
 main.scrollBy=vi.fn();return {view,main,region};
}
test.each([['PageDown',460],['PageUp',-460],['ArrowDown',40],['ArrowUp',-40],['Home',-5000],['End',5000]])('focused table forwards %s vertically', (key,top)=>{
 const {main,region}=setup();expect(fireEvent.keyDown(region,{key})).toBe(false);expect(main.scrollBy).toHaveBeenCalledWith({top,behavior:'instant'});
});
test('leaves horizontal keys, modifiers and interactive descendants to their native behavior',()=>{
 const {view,main,region}=setup();
 for(const key of ['ArrowLeft','ArrowRight','Enter',' ','Tab'])expect(fireEvent.keyDown(region,{key})).toBe(true);
 for(const modifier of ['altKey','ctrlKey','metaKey','shiftKey'])expect(fireEvent.keyDown(region,{key:'PageDown',[modifier]:true})).toBe(true);
 fireEvent.keyDown(view.getByRole('button'),{key:'ArrowDown'});fireEvent.keyDown(view.getByRole('textbox'),{key:'Home'});
 expect(main.scrollBy).not.toHaveBeenCalled();
});
