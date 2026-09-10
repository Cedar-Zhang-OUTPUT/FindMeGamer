// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,render,screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,expect,it} from 'vitest';
import {AnalysisInsights} from '../src/renderer/components/analyze/AnalysisInsights';
afterEach(cleanup);
it('keeps unavailable analysis compact while preserving its reason and stale status',async()=>{
 const user=userEvent.setup();render(<AnalysisInsights sourceStatus={{freshness:'stale'}} analysis={{audience:{status:'unavailable',reason:'No usable source'}}}/>);
 expect(screen.queryByRole('heading',{name:'At a glance'})).not.toBeInTheDocument();
 expect(screen.getByText('Previous analysis · stale')).toBeVisible();
 const summary=screen.getByText('Analysis unavailable');expect(summary.closest('details')).not.toHaveAttribute('open');
 await user.click(summary);expect(screen.getByText(/No usable source/)).toBeVisible();
});
