// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { createContext, useContext } from 'react';
import type { Row } from '../api';

// What the current page offers its tables and empty states without prop drilling:
// the create action (when the role allows it) and opening a resource drawer.
export type PageActions = {
  createLabel?: string;
  create?: () => void;
  open?: (row: Row) => void;
};

export const PageContext = createContext<PageActions>({});

export function usePageActions(): PageActions {
  return useContext(PageContext);
}
