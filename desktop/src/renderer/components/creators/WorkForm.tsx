import type { DesktopBridge } from '../../../shared/bridge';
import { CREATOR_PLATFORMS } from '../../../shared/creators';
import { DraftField, RepeatableFields, SourceComparison, type CreatorFormProps } from './CreatorForm';
import { LinkedGamePicker } from './LinkedGamePicker';
import { updateDraftField } from './creatorDraft';
export function WorkForm(props: CreatorFormProps & { api: Pick<DesktopBridge, 'games'> }) {
  const field = (key: string, extra: Partial<React.ComponentProps<typeof DraftField>> = {}) => <DraftField key={key} {...props} field={key} {...extra}/>;
  return <fieldset className="creator-form" disabled={props.disabled}><legend className="sr-only">Known work</legend>
    <div className="creator-form-grid">{field('work_name')}{field('content_title')}{field('content_type', { options: ['unverified', 'gameplay', 'livestream', 'review', 'commentary', 'trailer', 'news', 'other'] })}{field('source_url')}</div>
    <details className="creator-form-disclosure"><summary>Evidence and time</summary>{field('evidence_excerpt', { multiline: true })}{field('verification_notes', { multiline: true })}<div className="creator-form-grid">{field('timestamp_seconds', { numeric: true, placeholder: 'Unknown' })}{field('published_at', { placeholder: '2026-09-08T12:00:00+08:00' })}{field('collected_at', { placeholder: '2026-09-08T12:00:00+08:00' })}</div></details>
    <details className="creator-form-disclosure"><summary>Metrics and game</summary><RepeatableFields {...props} field="metrics" metric/><LinkedGamePicker api={props.api} value={props.draft.values.game_id as string | null} disabled={props.disabled} error={props.errors.game_id} onChange={value => props.onChange(updateDraftField(props.draft, 'game_id', value))}/></details>
    <details className="creator-form-disclosure"><summary>Platform and content ID</summary><div className="creator-form-grid">{field('platform', { options: ['', ...CREATOR_PLATFORMS] })}{field('content_id')}</div></details>
    <SourceComparison {...props}/>
  </fieldset>;
}
