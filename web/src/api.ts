// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
export type Row = Record<string, any>;
let csrf='';
export function setCSRF(value: string) {csrf=value}
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {super(message); this.status=status}
}
export async function api(path: string, body?: unknown, method?: string): Promise<any> {
  const response=await fetch(path,{method:method || (body===undefined?'GET':'POST'),credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:body===undefined?undefined:JSON.stringify(body)});
  const value=await response.json();
  if (!response.ok) throw new ApiError(value.error || `Request failed (${response.status})`, response.status);
  return value;
}
export type StreamEvent = {event: string; data: Row};
// POST that reads a text/event-stream response; each SSE frame is passed to onEvent.
export async function stream(path: string, body: unknown, onEvent: (e: StreamEvent) => void, signal?: AbortSignal): Promise<void> {
  const response=await fetch(path,{method:'POST',credentials:'same-origin',signal,headers:{'Content-Type':'application/json','X-CSRF-Token':csrf,Accept:'text/event-stream'},body:JSON.stringify(body)});
  if (!response.ok || !response.body) {
    let message=`Request failed (${response.status})`;
    try {message=(await response.json()).error || message} catch { /* not JSON */ }
    throw new ApiError(message, response.status);
  }
  const reader=response.body.getReader();
  const decoder=new TextDecoder();
  let buffer='';
  for (;;) {
    const {done,value}=await reader.read();
    if (done) break;
    buffer+=decoder.decode(value,{stream:true});
    let cut;
    while ((cut=buffer.indexOf('\n\n'))>=0) {
      const frame=buffer.slice(0,cut); buffer=buffer.slice(cut+2);
      let event='message'; const data: string[]=[];
      for (const line of frame.split('\n')) {
        if (line.startsWith('event:')) event=line.slice(6).trim();
        else if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
      }
      if (data.length) onEvent({event,data:JSON.parse(data.join('\n'))});
    }
  }
}
export function download(name: string, value: unknown, type='application/json') {
  const text=typeof value==='string'?value:JSON.stringify(value,null,2);
  const url=URL.createObjectURL(new Blob([text],{type}));
  const a=document.createElement('a'); a.href=url; a.download=name; a.click(); URL.revokeObjectURL(url);
}
export function money(value: number) {return new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',minimumFractionDigits:4}).format(value || 0)}
export function time(value: number) {return new Date(value*1000).toLocaleString()}
export function ago(value: number) {
  const s=Math.max(0,Date.now()/1000-value);
  if (s<60) return 'just now';
  if (s<3600) return `${Math.floor(s/60)}m ago`;
  if (s<86400) return `${Math.floor(s/3600)}h ago`;
  return `${Math.floor(s/86400)}d ago`;
}
