import { randomUUID } from 'node:crypto';
import { z } from 'zod';
import { InvalidRequest } from './errors.js';
import { deep_freeze, identity, integer, safe_number, text, valid_native_json } from './shared.js';

const FieldSchema = z.enum(['document_id', 'revision_id', 'language', 'kind', 'tag']);
const ScalarSchema = z.union([safe_number, z.boolean(), text(1024, false)]);
export const EqualityFilterSchema = z.strictObject({ op: z.enum(['eq', 'ne']), field: FieldSchema, value: ScalarSchema });
export const OrderFilterSchema = z.strictObject({ op: z.enum(['gt', 'gte', 'lt', 'lte']), field: FieldSchema, value: safe_number });
export const MembershipFilterSchema = z.strictObject({ op: z.literal('in'), field: FieldSchema, values: z.array(ScalarSchema).min(1).max(32) });
type Leaf = z.infer<typeof EqualityFilterSchema> | z.infer<typeof OrderFilterSchema> | z.infer<typeof MembershipFilterSchema>;
export type Filter = Leaf | { op: 'and' | 'or'; filters: Filter[] } | { op: 'not'; filter: Filter };
const FilterSchema: z.ZodType<Filter> = z.lazy(() => z.union([
  EqualityFilterSchema, OrderFilterSchema, MembershipFilterSchema,
  z.strictObject({ op: z.enum(['and', 'or']), filters: z.array(FilterSchema).min(1).max(16) }),
  z.strictObject({ op: z.literal('not'), filter: FilterSchema }),
]));

function bounded_request(input: unknown): boolean {
  if (!valid_native_json(input)) return false;
  if (input === null || typeof input !== 'object' || Array.isArray(input)) return false;
  const roots = (input as Record<string, unknown>).required_filters;
  if (roots === undefined) return true;
  if (!Array.isArray(roots) || roots.length > 16) return false;
  let count = 0;
  function visit(node: unknown, level: number): boolean {
    if (++count > 64 || level > 8 || node === null || typeof node !== 'object' || Array.isArray(node)) return false;
    const object = node as Record<string, unknown>;
    if (object.op === 'not') return visit(object.filter, level + 1);
    if (object.op === 'and' || object.op === 'or') {
      return Array.isArray(object.filters) && object.filters.length >= 1 && object.filters.length <= 16
        && object.filters.every(child => visit(child, level + 1));
    }
    return true;
  }
  return roots.every(root => visit(root, 1));
}

export const LimitsSchema = z.strictObject({
  deadline_ms: integer(1, 300000).default(10000),
  max_attempts: integer(1, 10).default(3),
  max_subqueries: integer(1, 16).default(4),
  max_candidates: integer(1, 10000).default(200),
  max_context_tokens: integer(1, 1000000).default(2000),
  max_provider_calls: integer(0, 1000).default(16),
  max_spend_usd: safe_number.min(0).max(1000000).nullable().default(null),
});
export const OutputProfileSchema = z.strictObject({
  renderer: identity.default('cragkit.context.v1'),
  tokenizer: identity.nullable().default(null),
  envelope_reserve_tokens: integer(0, 1000000).default(256),
  counting_mode: z.enum(['estimated', 'strict']).default('estimated'),
}).refine(value => value.counting_mode !== 'strict' || value.tokenizer !== null);
const common = {
  schema_version: z.literal('0.1').default('0.1'),
  request_id: identity.default(() => randomUUID()),
  query: text(16384),
  collection: text(128),
  search_hints: z.array(text(256)).max(8).default([]),
};
export const RequestSchema = z.custom<unknown>(bounded_request).pipe(z.strictObject({
  ...common,
  required_filters: z.array(FilterSchema).max(16).default([]),
  limits: LimitsSchema.prefault({}),
  output_profile: OutputProfileSchema.prefault({}),
})).transform(deep_freeze);
export const ToolRequestSchema = z.custom<unknown>(valid_native_json).pipe(z.strictObject(common)).transform(deep_freeze);
export const TrustedScopeSchema = z.custom<unknown>(valid_native_json).pipe(z.strictObject({
  tenant_id: identity,
  principal_id: identity,
  authorization_revision: identity,
  grant_ids: z.array(identity).max(64).default([]),
})).transform(deep_freeze);
export type RetrievalRequest = z.infer<typeof RequestSchema>;
export type ToolRequest = z.infer<typeof ToolRequestSchema>;
export type TrustedScope = z.infer<typeof TrustedScopeSchema>;
export type Limits = z.infer<typeof LimitsSchema>;
export type OutputProfile = z.infer<typeof OutputProfileSchema>;

function safely_parse<T>(schema: z.ZodType<T>, input: unknown): T {
  try { return schema.parse(input); } catch { throw new InvalidRequest(); }
}
export const parse_request = (input: unknown): RetrievalRequest => safely_parse(RequestSchema, input);
export const parse_tool_request = (input: unknown): ToolRequest => safely_parse(ToolRequestSchema, input);
export const parse_scope = (input: unknown): TrustedScope => safely_parse(TrustedScopeSchema, input);
