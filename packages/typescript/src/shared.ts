import { z } from 'zod';

export type DeepReadonly<T> = T extends readonly (infer U)[]
  ? readonly DeepReadonly<U>[]
  : T extends object ? { readonly [K in keyof T]: DeepReadonly<T[K]> } : T;

export function deep_freeze<T>(value: T): DeepReadonly<T> {
  if (value !== null && typeof value === 'object') {
    for (const child of Object.values(value)) deep_freeze(child);
    Object.freeze(value);
  }
  return value as DeepReadonly<T>;
}

export const safe_number = z.number().min(-Number.MAX_SAFE_INTEGER).max(Number.MAX_SAFE_INTEGER);
export const integer = (min: number, max: number) => safe_number.int().min(min).max(max);
export const text = (bytes: number, nonblank = true) => z.string().refine(
  value => !/[\uD800-\uDFFF]/u.test(value) && Buffer.byteLength(value, 'utf8') <= bytes
    && (!nonblank || /[^ \t\r\n\f\v]/.test(value)),
  { message: 'Invalid text.' },
);
export const input_text = (bytes: number, nonblank = true) => text(bytes, nonblank).refine(
  value => !value.includes('\u0000'),
  { message: 'Invalid text.' },
);
export const identity = input_text(256);

export function valid_native_json(input: unknown): boolean {
  const ancestors = new Set<object>();
  let nodes = 0;
  function visit(value: unknown, depth: number): boolean {
    if (++nodes > 4096 || depth > 32) return false;
    if (value === null || typeof value === 'boolean') return true;
    if (typeof value === 'number') return Number.isFinite(value) && Math.abs(value) <= Number.MAX_SAFE_INTEGER;
    if (typeof value === 'string') return !/[\uD800-\uDFFF]/u.test(value);
    if (typeof value !== 'object' || ancestors.has(value)) return false;
    if (!Array.isArray(value) && Object.getPrototypeOf(value) !== Object.prototype && Object.getPrototypeOf(value) !== null) return false;
    if (Object.getOwnPropertySymbols(value).length) return false;
    if (Array.isArray(value) && value.length > 4096) return false;
    ancestors.add(value);
    try {
      const descriptors = Object.getOwnPropertyDescriptors(value);
      if (Array.isArray(value) && Object.keys(value).length !== value.length) return false;
      for (const [key, descriptor] of Object.entries(descriptors)) {
        if (Array.isArray(value) && key === 'length') continue;
        if (!('value' in descriptor) || !descriptor.enumerable || !visit(descriptor.value, depth + 1)) return false;
      }
      return true;
    } finally { ancestors.delete(value); }
  }
  try { return visit(input, 0); } catch { return false; }
}
