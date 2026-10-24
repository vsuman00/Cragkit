/** ASCII symbol extraction profile; ordinary words have no exact-identifier vote. */
import { InvalidRequest } from './errors.js';
export const IDENTIFIER_PROFILE = 'identifier_ascii_v1' as const;
export function extract_identifiers(text: string): readonly string[] {
  const matches = text.match(/[A-Za-z_][A-Za-z0-9_]*(?:[.:/-]+[A-Za-z0-9_]+)*(?:\+\+|#)?/g) ?? [];
  return Object.freeze([...new Set(matches.filter(value => value.length <= 256 && /[0-9_.:/+#-]|[a-z][A-Z]/.test(value)))].sort((a, b) => Buffer.compare(Buffer.from(a), Buffer.from(b))));
}
export function validate_identifier(value: unknown): string {
  if (typeof value !== 'string' || value.length > 256) throw new InvalidRequest();
  const extracted = extract_identifiers(value);
  if (extracted.length !== 1 || extracted[0] !== value) throw new InvalidRequest();
  return value;
}
