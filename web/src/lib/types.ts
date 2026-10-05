import type { Row } from '../api';

export type Act = <T>(fn: () => Promise<T>) => Promise<T | null>;

export type Collections = Record<string, Row[]>;
