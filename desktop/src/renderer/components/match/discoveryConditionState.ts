import type {CandidateFilters,DiscoveryBudgets,FollowerRange,PlanCreate} from '../../../shared/match';

export const LANGUAGES=[
  ['en','English','英语'],['ja','Japanese','日语'],['ko','Korean','韩语'],['zh-Hans','Simplified Chinese','简体中文'],['zh-Hant','Traditional Chinese','繁体中文'],
  ['es','Spanish','西班牙语'],['pt','Portuguese','葡萄牙语'],['fr','French','法语'],['de','German','德语'],['it','Italian','意大利语'],['ru','Russian','俄语'],
  ['ar','Arabic','阿拉伯语'],['id','Indonesian','印尼语'],['th','Thai','泰语'],['vi','Vietnamese','越南语'],
] as const;
export const COUNTRIES=[
  ['US','United States','美国'],['CA','Canada','加拿大'],['GB','United Kingdom','英国'],['AU','Australia','澳大利亚'],['NZ','New Zealand','新西兰'],
  ['JP','Japan','日本'],['KR','South Korea','韩国'],['DE','Germany','德国'],['FR','France','法国'],['IT','Italy','意大利'],['ES','Spain','西班牙'],
  ['PT','Portugal','葡萄牙'],['NL','Netherlands','荷兰'],['SE','Sweden','瑞典'],['NO','Norway','挪威'],['DK','Denmark','丹麦'],['FI','Finland','芬兰'],
  ['PL','Poland','波兰'],['BR','Brazil','巴西'],['MX','Mexico','墨西哥'],['IN','India','印度'],['ID','Indonesia','印度尼西亚'],['TH','Thailand','泰国'],
  ['VN','Vietnam','越南'],['MY','Malaysia','马来西亚'],['SG','Singapore','新加坡'],['PH','Philippines','菲律宾'],['TR','Turkey','土耳其'],
  ['SA','Saudi Arabia','沙特阿拉伯'],['AE','United Arab Emirates','阿联酋'],
] as const;
export type Choice=readonly [code:string,label:string,...aliases:string[]];
export const FOLLOWER_PRESETS:{label:string;range:FollowerRange}[]=[
  {label:'0–999',range:{minimum:0,maximum:999}},{label:'1,000–9,999',range:{minimum:1000,maximum:9999}},
  {label:'10,000–49,999',range:{minimum:10000,maximum:49999}},{label:'50,000–99,999',range:{minimum:50000,maximum:99999}},
  {label:'100,000–499,999',range:{minimum:100000,maximum:499999}},{label:'500,000–999,999',range:{minimum:500000,maximum:999999}},
  {label:'1,000,000+',range:{minimum:1000000,maximum:null}},
];
export const BUDGETS:{key:keyof DiscoveryBudgets;label:string;value:number;maximum:number}[]=[
  {key:'batch_target',label:'Batch target',value:100,maximum:100},{key:'result_limit',label:'Result limit',value:600,maximum:600},
  {key:'batch_request_budget',label:'Batch request budget',value:20,maximum:40},{key:'batch_scan_budget',label:'Batch scan budget',value:1000,maximum:2000},
  {key:'total_request_budget',label:'Total request budget',value:120,maximum:240},{key:'total_scan_budget',label:'Total scan budget',value:6000,maximum:12000},
];
export function filtersFrom(value:PlanCreate):Required<CandidateFilters>{
  return {countries:[],languages:[],pending_country_labels:[],follower_ranges:[],include_unknown_country:true,include_unknown_language:true,include_unknown_followers:true,contact:'any',...value.filters};
}
export function defaultConditions():PlanCreate{
  return {mode:'discover',platforms:['youtube','x'],keywords:[],filters:filtersFrom({mode:'discover',platforms:['youtube','x']}),...Object.fromEntries(BUDGETS.map(({key,value})=>[key,value]))};
}
export function sameRange(a:FollowerRange,b:FollowerRange){return (a.minimum??null)===(b.minimum??null)&&(a.maximum??null)===(b.maximum??null);}
export function rangeError(ranges:FollowerRange[]):string|undefined{
  if(ranges.length>7)return 'Choose up to seven ranges.';
  for(const range of ranges){
    const {minimum,maximum}=range;
    if(minimum==null&&maximum==null)return 'Enter a minimum or maximum.';
    if([minimum,maximum].some(value=>value!=null&&(!Number.isSafeInteger(value)||value<0)))return 'Use nonnegative whole numbers.';
    if(maximum!=null&&(minimum??0)>maximum)return 'Minimum must not exceed maximum.';
  }
}
export const cleanText=(value:string,limit:number)=>Boolean(value.trim())&&value.length<=limit&&!/[\u0000-\u001f\u007f]/.test(value);
export function validateConditions(value:PlanCreate):Record<string,string>{
  const errors:Record<string,string>={};
  if(!value.platforms.length||value.platforms.length>2||new Set(value.platforms).size!==value.platforms.length||value.platforms.some(platform=>!['youtube','x'].includes(platform)))errors.platforms='Choose YouTube or X.';
  if((value.keywords??[]).length>20||(value.keywords??[]).some(word=>!cleanText(word,100)))errors.keywords='Use up to 20 keywords, each 1–100 characters.';
  const filters=filtersFrom(value);
  if(filters.countries.length>30||filters.countries.some(code=>!/^[A-Z]{2}$/.test(code)))errors.countries='Use up to 30 two-letter country codes.';
  if(filters.languages.length>30||filters.languages.some(language=>!cleanText(language,64)))errors.languages='Use up to 30 languages, each 1–64 characters.';
  if(filters.pending_country_labels.length>30||filters.pending_country_labels.some(label=>!cleanText(label,100)))errors.pending_country_labels='Use up to 30 pending regions, each 1–100 characters.';
  if(!['any','available','missing'].includes(filters.contact))errors.contact='Choose an email availability option.';
  const invalidRange=rangeError(filters.follower_ranges);if(invalidRange)errors.follower_ranges=invalidRange;
  for(const {key,maximum,value:fallback} of BUDGETS){const number=value[key]??fallback;if(!Number.isSafeInteger(number)||number<1||number>maximum)errors[key]=`Use a whole number from 1 to ${maximum.toLocaleString('en')}.`;}
  return errors;
}
