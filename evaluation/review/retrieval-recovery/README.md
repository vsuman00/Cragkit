# Recovery packet for human review

This separate draft contains five synthetic source revisions and six proposed questions, covering eight facets and seven support references. Human review was approved by the project user on 2026-11-03 with the explicit reply "I approved" to the six-question/eight-facet review request. The dataset records reviewer `project-user`. Read every source and every facet below, including the absent-answer and conflicting claims. Mechanical checks cannot approve these judgments.

The author agent was `/root/transport_pacing`; `/root/transport_diagnostics` independently read the sources before the proposed labels and assembled this guide. Both agents are exposed to this packet. These small synthetic examples are not a blind external benchmark and establish no retrieval quality, performance or release result. The original attempted packet is already exposed; this draft does not restore its unseen status. The new family IDs are disjoint from the old manifest, which does not prove broad semantic independence.

This directory is an approved label-review artifact; live execution still requires its trusted seal/profile and frozen candidate/runtime identity. It does not change original labels, seals, targets, runtime bindings, recordings or dispatch authorization. Human approval is recorded; accepted packet identity and the planned candidate/input/runtime refreeze remain separate gates. A new paid run needs its own recorded decision and budget.

Review [the manifest](corpus/manifest.json) and [all proposed question labels](questions/held_out.json) alongside this guide. All documents use collection `customer-operations` and split `held_out`. Byte spans below are half-open UTF-8 offsets `[start,end)`, not character positions. The source blocks reproduce the full source text, including the final newline; the linked files and digests define exact bytes.

## Full source revisions

### tenant-orchid / support-routing / r1

[Full source file](corpus/orchid-routing-r1.md). Family `recovery-support-routing`; active `false`. SHA-256 `455b6c71790ccc6f09f247735be1bb49f32f456f30bbd969b872c76a60aad11f`.

```text
# Orchid support routing, revision 1

This historical policy applies to Orchid customer support requests.
Route damaged-package reports to the Birch desk.
Acknowledge damaged-package reports within eight business hours.
```

### tenant-orchid / support-routing / r2

[Full source file](corpus/orchid-routing-r2.md). Family `recovery-support-routing`; active `true`. SHA-256 `20e3f8f782fe21c01089c7eb661bb4f30fee53df8d14b6ae61124bba7606cbc2`.

```text
# Orchid support routing, revision 2

This current policy applies to Orchid customer support requests.
Route damaged-package reports to the Willow desk.
Acknowledge damaged-package reports within three business hours.
```

### tenant-cobalt / support-routing / r1

[Full source file](corpus/cobalt-routing-r1.md). Family `recovery-support-routing`; active `true`. SHA-256 `021f7272431edad67d5c82dce39f6e4c925cbe7798922dd30b4000740a8d9c0b`.

```text
# Cobalt support routing, revision 1

This current policy applies to Cobalt customer support requests.
Route damaged-package reports to the Café 🙂 desk.
Acknowledge damaged-package reports within six business hours.
```

### tenant-orchid / delivery-guide / r1

[Full source file](corpus/orchid-delivery-guide-r1.md). Family `recovery-delivery-window`; active `true`. SHA-256 `0bb2fa73f1abf59262e076142b38dd7598d3467505f9715e98a52fadef810c74`.

```text
# Orchid delivery guide, revision 1

This current policy applies to all Orchid standard parcels.
The delivery window for standard parcels is two business days after dispatch.
This guide and the delivery bulletin have equal authority; neither overrides the other.
```

### tenant-orchid / delivery-bulletin / r1

[Full source file](corpus/orchid-delivery-bulletin-r1.md). Family `recovery-delivery-window`; active `true`. SHA-256 `a854a76b21c2ecfbf00b515cd76b18892c30b9dc14cfa4fa0caa7cc73383f7a1`.

```text
# Orchid delivery bulletin, revision 1

This current policy applies to all Orchid standard parcels.
The delivery window for standard parcels is four business days after dispatch.
This bulletin and the delivery guide have equal authority; neither overrides the other.
```

## Question and facet review

An empty filter list uses only active revisions within the question tenant and collection. An explicit revision filter permits the identified historical revision. Tenant boundaries still apply when document and revision IDs coincide.

### recovery-q01

Under the current Orchid support policy, which desk receives damaged-package reports and how soon must they be acknowledged?

Tenant `tenant-orchid`; collection `customer-operations`. Proposed answerability: `answerable`. Required equality filters: `[]`.

The current Orchid revision explicitly names Willow and three business hours. Historical Birch/eight-hour statements cannot replace it, and Cobalt text is outside this tenant.


- `recovery-q01-route`: Which desk receives the reports? Proposed state: `supported`.

  Source [support-routing / r2](corpus/orchid-routing-r2.md), span `[103,152)`, source digest `20e3f8f782fe21c01089c7eb661bb4f30fee53df8d14b6ae61124bba7606cbc2`. Exact excerpt:

  > Route damaged-package reports to the Willow desk.


- `recovery-q01-ack`: How soon must the reports be acknowledged? Proposed state: `supported`.

  Source [support-routing / r2](corpus/orchid-routing-r2.md), span `[153,217)`, source digest `20e3f8f782fe21c01089c7eb661bb4f30fee53df8d14b6ae61124bba7606cbc2`. Exact excerpt:

  > Acknowledge damaged-package reports within three business hours.

### recovery-q02

In revision 1 of the Orchid support-routing policy, which desk received damaged-package reports?

Tenant `tenant-orchid`; collection `customer-operations`. Proposed answerability: `answerable`. Required equality filters: `[{"op": "eq", "field": "document_id", "value": "support-routing"}, {"op": "eq", "field": "revision_id", "value": "r1"}]`.

The explicit document and revision filters select inactive Orchid r1. Its Birch statement answers the historical question; Orchid r2 and Cobalt r1 are excluded.


- `recovery-q02-route`: Which desk was specified in revision 1? Proposed state: `supported`.

  Source [support-routing / r1](corpus/orchid-routing-r1.md), span `[106,154)`, source digest `455b6c71790ccc6f09f247735be1bb49f32f456f30bbd969b872c76a60aad11f`. Exact excerpt:

  > Route damaged-package reports to the Birch desk.

### recovery-q03

Under the current Cobalt support policy, which desk receives damaged-package reports?

Tenant `tenant-cobalt`; collection `customer-operations`. Proposed answerability: `answerable`. Required equality filters: `[]`.

The active Cobalt revision names the Café 🙂 desk. The identically named Orchid document is outside the tenant. Accented and emoji text must retain exact bytes.


- `recovery-q03-route`: Which Cobalt desk receives the reports? Proposed state: `supported`.

  Source [support-routing / r1](corpus/cobalt-routing-r1.md), span `[103,156)`, source digest `021f7272431edad67d5c82dce39f6e4c925cbe7798922dd30b4000740a8d9c0b`. Exact excerpt:

  > Route damaged-package reports to the Café 🙂 desk.

### recovery-q04

Who is the named owner of the Orchid damaged-package escalation process?

Tenant `tenant-orchid`; collection `customer-operations`. Proposed answerability: `unanswerable`. Required equality filters: `[]`.

No active authorized Orchid source names an escalation process owner. A routing desk is a destination, not a named owner. This is absence within the packet, not proof that an owner does not exist.


- `recovery-q04-owner`: Who is the named escalation process owner? Proposed state: `missing`.

  No support span is proposed. Review the scoped absence judgment against the full eligible sources above.

### recovery-q05

According to the Orchid delivery guide, what is the standard-parcel delivery window and who is the delivery manager?

Tenant `tenant-orchid`; collection `customer-operations`. Proposed answerability: `partially_answerable`. Required equality filters: `[{"op": "eq", "field": "document_id", "value": "delivery-guide"}]`.

The document filter limits this question to the guide. Its two-business-day claim supports the requested window according to that guide. It names no delivery manager. The excluded bulletin cannot fill the missing facet or settle broader policy.


- `recovery-q05-window`: What delivery window does the guide specify? Proposed state: `supported`.

  Source [delivery-guide / r1](corpus/orchid-delivery-guide-r1.md), span `[97,174)`, source digest `0bb2fa73f1abf59262e076142b38dd7598d3467505f9715e98a52fadef810c74`. Exact excerpt:

  > The delivery window for standard parcels is two business days after dispatch.


- `recovery-q05-manager`: Who is the delivery manager? Proposed state: `missing`.

  No support span is proposed. Review the scoped absence judgment against the full eligible sources above.

### recovery-q06

What delivery window do the current Orchid policies establish for standard parcels?

Tenant `tenant-orchid`; collection `customer-operations`. Proposed answerability: `partially_answerable`. Required equality filters: `[]`.

Both delivery documents are active, authorized and apply to all Orchid standard parcels. One says two business days, the other four. Both explicitly declare equal authority and no override. The packet offers no way to choose one as the established window.


- `recovery-q06-window`: What is the standard-parcel delivery window? Proposed state: `conflicting`.

  Source [delivery-guide / r1](corpus/orchid-delivery-guide-r1.md), span `[97,174)`, source digest `0bb2fa73f1abf59262e076142b38dd7598d3467505f9715e98a52fadef810c74`. Exact excerpt:

  > The delivery window for standard parcels is two business days after dispatch.

  Source [delivery-bulletin / r1](corpus/orchid-delivery-bulletin-r1.md), span `[100,178)`, source digest `a854a76b21c2ecfbf00b515cd76b18892c30b9dc14cfa4fa0caa7cc73383f7a1`. Exact excerpt:

  > The delivery window for standard parcels is four business days after dispatch.


## Human review decision

Review all five source revisions and all six questions, including each of the eight facets. Confirm scope, current and historical selection, exact excerpts, supported claims, missing owner/manager judgments and the two-source conflict. Request corrections where needed; schema validity alone does not approve the labels.

Record the human reviewer identity, decision, corrections and reviewed fixture revision through the coordinator. The project user supplied that decision on 2026-11-03. The prior pending revision is preserved in [the approval record](approval.json); agent review did not supply approval. The coordinator follows the protocol's separate sealing and evaluation gates.

A useful failure example is q03: quoting the Orchid Willow desk would be wrong even though the document ID matches. Optional exercise: explain why the Café 🙂 excerpt uses more UTF-8 bytes than characters. Learning practice remains unassessed.
