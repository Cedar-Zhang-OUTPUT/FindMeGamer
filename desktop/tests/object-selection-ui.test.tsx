// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {useState} from 'react';
import {cleanup,render,screen,within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,expect,it,vi} from 'vitest';
import {GameForm} from '../src/renderer/components/GameForm';
import {draftFrom,newReference} from '../src/renderer/components/gameDraft';
import {SavedListComposer} from '../src/renderer/components/match/SavedListComposer';
import {ScopedSelectionActions} from '../src/renderer/components/SelectionActions';
afterEach(cleanup);
it('selects only listed references without changing the form, keeping outside IDs and new references unselected',async()=>{
 const user=userEvent.setup(),onChange=vi.fn(),draft={...draftFrom(null),references:[{...newReference(),localId:'a',name:'A'},{...newReference(),localId:'b',name:'B'}]};
 function Form({extra=false}:{extra?:boolean}){const [ids,setIds]=useState(['outside','a']);return <><output>{ids.join(',')}</output><GameForm base={null} draft={extra?{...draft,references:[...draft.references,{...newReference(),localId:'c',name:'C'}]}:draft} errors={{}} disabled={false} onChange={onChange} selection={{ids,onChange:setIds}}/></>;}
 const {rerender}=render(<Form/>);const controls=screen.getByRole('group',{name:'Listed reference works selection'});
 await user.click(within(controls).getByRole('button',{name:'Select all'}));expect(screen.getByRole('status')).toHaveTextContent('outside,a,b');
 rerender(<Form extra/>);expect(screen.getByRole('checkbox',{name:'Use reference C'})).not.toBeChecked();
 await user.click(within(controls).getByRole('button',{name:'Deselect all'}));expect(screen.getByRole('status')).toHaveTextContent(/^outside$/);expect(onChange).not.toHaveBeenCalled();
});
it('saved-list actions preserve marked creators outside current loaded scope',async()=>{
 const user=userEvent.setup(),onSave=vi.fn();
 function Composer(){const [draft,setDraft]=useState({queryId:'q',name:'Team',ids:['outside','a']});return <><output>{draft.ids.join(',')}</output><SavedListComposer draft={draft} loadedIds={['a','b']} onChange={setDraft} onSave={onSave} onCancel={()=>{}} onMarkLoaded={()=>{}} onClear={()=>{}} disabled={false} current/></>;}
 render(<Composer/>);await user.click(screen.getByRole('button',{name:'Deselect all'}));expect(screen.getByRole('status')).toHaveTextContent(/^outside$/);
 await user.click(screen.getByRole('button',{name:'Select all'}));expect(screen.getByRole('status')).toHaveTextContent('outside,a,b');expect(onSave).not.toHaveBeenCalled();
});
it('handles empty, all-selected, disabled and over-limit object scopes without partial selection',async()=>{
 const onChange=vi.fn(),props={scope:'Items',ids:['a','b'],selected:['outside'],onChange,limit:2};
 const {rerender}=render(<ScopedSelectionActions {...props}/>);expect(screen.getByRole('button',{name:'Select all'})).toBeDisabled();expect(screen.getByRole('button',{name:'Deselect all'})).toBeDisabled();
 rerender(<ScopedSelectionActions {...props} selected={['a','b']}/>);expect(screen.getByRole('button',{name:'Select all'})).toBeDisabled();expect(screen.getByRole('button',{name:'Deselect all'})).toBeEnabled();
 rerender(<ScopedSelectionActions {...props} selected={['a']} disabled/>);expect(screen.getByRole('button',{name:'Deselect all'})).toBeDisabled();
 rerender(<ScopedSelectionActions {...props} ids={[]}/>);expect(screen.getByRole('button',{name:'Select all'})).toBeDisabled();expect(onChange).not.toHaveBeenCalled();
});
