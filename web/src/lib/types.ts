// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import type { Row } from '../api';

export type Act = <T>(fn: () => Promise<T>, success?: string) => Promise<T | null>;

export type Collections = Record<string, Row[]>;
