import { DraftField, SourceComparison, type CreatorFormProps } from './CreatorForm';
export function ContactForm(props: CreatorFormProps) {
  return <fieldset className="creator-form" disabled={props.disabled}><legend className="sr-only">Email contact</legend>
    <div className="creator-form-grid"><DraftField {...props} field="email"/><DraftField {...props} field="purpose"/></div><DraftField {...props} field="is_active"/>
    <details className="creator-form-disclosure"><summary>Source and verification notes</summary><DraftField {...props} field="source_url"/><DraftField {...props} field="verification_notes" multiline/></details>
    <SourceComparison {...props}/>
  </fieldset>;
}
