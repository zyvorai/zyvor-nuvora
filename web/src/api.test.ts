// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import {afterEach,describe,expect,it,vi} from 'vitest';
import {api,money,setCSRF} from './api';
afterEach(()=>vi.unstubAllGlobals());
describe('API boundary',()=>{
 it('sends session credentials and the CSRF token',async()=>{
  const fetch=vi.fn().mockResolvedValue({ok:true,json:async()=>({ok:true})});vi.stubGlobal('fetch',fetch);setCSRF('csrf-value');
  await api('/api/models',{name:'test'});
  expect(fetch.mock.calls[0][1].credentials).toBe('same-origin');
  expect(fetch.mock.calls[0][1].headers['X-CSRF-Token']).toBe('csrf-value');
 });
 it('surfaces server refusal instead of claiming success',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:false,status:403,json:async()=>({error:'Forbidden'})}));
  await expect(api('/api/models',{})).rejects.toThrow('Forbidden');
 });
 it('uses GET for a read',async()=>{
  const fetch=vi.fn().mockResolvedValue({ok:true,json:async()=>({items:[]})});vi.stubGlobal('fetch',fetch);
  await api('/api/models');expect(fetch.mock.calls[0][1].method).toBe('GET');
 });
 it('formats zero spend without inventing charges',()=>{expect(money(0)).toContain('0.0000')});
});
