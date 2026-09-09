// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,render,screen} from '@testing-library/react';
import {afterEach,expect,it} from 'vitest';
import {AnalysisInsights} from '../src/renderer/components/analyze/AnalysisInsights';
afterEach(cleanup);
it('renders supported AI observations and actual X coverage without claiming full history',()=>{
 render(<AnalysisInsights brief={{content_summary:{status:'available',kind:'ai_inference',text:'Puzzle commentary',cited_source_ids:['91001']},brand_safety:{status:'unavailable',reason:'Insufficient evidence'}}} analysis={{}} sourceStatus={{coverage:'recent_account_posts',sample_size:21,post_limit:50,more_available:true}}/>);
 expect(screen.getByText('Puzzle commentary')).toBeVisible();expect(screen.getByText('AI interpretation')).toBeVisible();expect(screen.getByText(/21 recent original posts/)).toBeVisible();expect(screen.getByText(/More posts available/)).toBeVisible();expect(screen.getByText(/Insufficient evidence/)).not.toBeVisible();
});
it('does not manufacture insight cards from absent values',()=>{const{container}=render(<AnalysisInsights brief={{}} analysis={{}}/>);expect(container).toBeEmptyDOMElement();});
