// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { describe, expect, it } from 'vitest';
import { parseFields } from './ExtractCard';
import { userContent } from '../pages/Playground';

describe('parseFields', () => {
  it('parses name, type and description', () => {
    expect(parseFields('invoice: string - Invoice id\ntotal: number\n\ndue')).toEqual({
      fields: { invoice: { type: 'string', description: 'Invoice id' }, total: { type: 'number', description: '' }, due: { type: 'string', description: '' } },
    });
  });
  it('rejects bad names, unknown types and empty specs', () => {
    expect(parseFields('Bad Name: string').error).toMatch(/name: type/);
    expect(parseFields('total: money').error).toMatch(/Unknown type/);
    expect(parseFields('  ').error).toMatch(/1–30/);
  });
});

describe('userContent', () => {
  it('keeps plain text without images and builds parts with them', () => {
    expect(userContent('hi', [])).toBe('hi');
    expect(userContent('hi', ['data:image/png;base64,AA=='])).toEqual([
      { type: 'text', text: 'hi' },
      { type: 'image_url', image_url: { url: 'data:image/png;base64,AA==' } },
    ]);
  });
});
