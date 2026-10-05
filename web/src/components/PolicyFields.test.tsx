// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
// @vitest-environment jsdom
import { useState } from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { Row } from '../api';
import PolicyFields, { splitList } from './PolicyFields';

afterEach(cleanup);

let latest: Row = {};
function Harness() {
  const [data, setData] = useState<Row>({ blocked_topics: [] });
  latest = data;
  return <PolicyFields data={data} set={(k, v) => setData((d) => ({ ...d, [k]: v }))} chatModels={[{ id: 'm1', name: 'Safety', provider: 'openai' }, { id: 'd', name: 'Demo', provider: 'demo' }]} />;
}

describe('PolicyFields', () => {
  it('splits comma lists', () => {
    expect(splitList(' a, ,b ,c')).toEqual(['a', 'b', 'c']);
  });

  it('edits entities, filters, grounding and the classifier', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: 'Choose entity types' }));
    expect(latest.pii_entities).toEqual({ email: 'mask', card: 'mask' });
    fireEvent.change(screen.getByLabelText('ssn action'), { target: { value: 'block' } });
    fireEvent.change(screen.getByLabelText('email action'), { target: { value: 'off' } });
    expect(latest.pii_entities).toEqual({ card: 'mask', ssn: 'block' });

    fireEvent.click(screen.getByRole('button', { name: /Add filter/ }));
    fireEvent.change(screen.getByLabelText('Filter pattern'), { target: { value: 'TCK-\\d+' } });
    expect(latest.regex_filters).toEqual([{ name: '', pattern: 'TCK-\\d+', action: 'mask' }]);

    fireEvent.change(screen.getByLabelText(/Grounding threshold/), { target: { value: '0.7' } });
    expect(latest.grounding_threshold).toBe(0.7);

    const select = screen.getByLabelText('Model') as HTMLSelectElement;
    expect([...select.options].map((o) => o.textContent)).not.toContain('Demo');
    fireEvent.change(select, { target: { value: 'm1' } });
    fireEvent.click(screen.getByLabelText('violence'));
    expect(latest.classifier_model).toBe('m1');
    expect(latest.classifier_categories).toEqual(['violence']);
  });
});
