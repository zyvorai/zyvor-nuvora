export type Row = Record<string, any>;
let csrf='';
export function setCSRF(value: string) {csrf=value}
export async function api(path: string, body?: unknown, method?: string): Promise<any> {
  const response=await fetch(path,{method:method || (body===undefined?'GET':'POST'),credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:body===undefined?undefined:JSON.stringify(body)});
  const value=await response.json();
  if (!response.ok) throw new Error(value.error || `Request failed (${response.status})`);
  return value;
}
export function download(name: string, value: unknown) {
  const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));
  const a=document.createElement('a'); a.href=url; a.download=name; a.click(); URL.revokeObjectURL(url);
}
export function money(value: number) {return new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',minimumFractionDigits:4}).format(value || 0)}
export function time(value: number) {return new Date(value*1000).toLocaleString()}
