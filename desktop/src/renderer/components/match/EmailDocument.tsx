import {previewDocument} from '../../../shared/mail-preview';
const presentation='<style>body{margin:24px;color:#172a42;background:#fffdf9;font:15px/1.65 system-ui,sans-serif;overflow-wrap:anywhere}p{margin:0 0 14px}a{color:#067786}mark,span[background-color]{background:#dbeee9;color:inherit;border-radius:3px;padding:1px 3px}mark[data-slot=channelName]{background:#e6e2f8}mark[data-slot=reference]{background:#fae4d5}mark[data-slot=observation]{background:#e0ecfa}</style>';
export function EmailDocument({html,title='Email preview'}:{html:string;title?:string}){
  return <iframe className="email-document" title={title} sandbox="" referrerPolicy="no-referrer" srcDoc={previewDocument(presentation+html)}/>;
}
