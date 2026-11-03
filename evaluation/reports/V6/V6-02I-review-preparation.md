# V6-02I1 recovery review preparation

Status: COMPLETE for draft preparation and mechanical validation. Actual human
label review remains PENDING; V6-02 acceptance and full V6 remain incomplete.

For example, the proposed Cobalt question must use the Cobalt source despite an
Orchid document sharing its document/revision IDs. The full review guide shows
both texts so the human reviewer can assess that boundary.

The [separate review guide](../../review/retrieval-recovery/README.md) includes
all five full synthetic source revisions, six questions, eight facets, filters,
seven exact support spans and explanations of missing/conflicting labels.
Sol author owned only new source/manifest/question files. Sol reviewer derived
judgments from sources before reading labels, then independently checked the
labels and assembled the guide. Both communicated directly and returned ownership
to root. Root inspected their reports and actual files, then ran the existing
mechanical corpus checker, native packet validator and independent scoring-input
validator. No reviewer supplied human approval.

The proposed family IDs are disjoint from the original manifest. Three questions
are answerable, one unanswerable and two partially answerable; the eight facets
contain five supported, two missing and one conflicting label. Agent author,
reviewer and root exposure is explicit. This is a small, pre-exposed synthetic
packet, not a blind external benchmark or a general retrieval-quality claim.
No original held-out result informed the author/reviewer's proposed labels.

## Actual validation

Root copied the bounded new corpus and pending question data into a temporary
checker layout, with an empty pending development dataset solely to adapt the
existing checker. That temporary adapter is not proposed execution input and was
removed automatically. `validate_corpus(..., include_held_out=True)` passed:
five documents, six questions, eight facets and seven support spans. Setting
`require_human_review=True` correctly failed with `human_review_pending`.
A second temporary probe gave only the empty synthetic development adapter
approved fixture metadata so validation reached the held-out gate itself; that
gate also refused the actual pending held-out data. No approval metadata was
changed in any project dataset or retained as an actual human decision.
The label-free projection passed `retrieval_evaluation.validate_packet`; the
complete proposed labels passed `evaluation_scoring._labels` against it.
No retrieval, assessment, model request or score evaluation was run.

The [safe validation record](V6-02I-review-verification.json) pins every source,
manifest, question and guide digest, plus the overall review revision. It records
family disjointness, schema acceptance and refusal of pending human review.
Structural validity cannot establish relevance, genuine absence or conflict;
these judgments remain the user's review task. The actual approval request
links the complete guide and asks for all six questions/eight facets, rather
than treating prior approval of the original 30 labels as approval of this draft.

The existing original corpus/labels/seal, admission and unsealed failed tape are
unchanged. The production binder still accepts only its original approved seal;
this draft is not wired into execution or silently approved. The original
16-file seal check passed after the transport correction. No candidate source/
runtime refreeze or paid rerun occurred here. A later approved packet needs its
own sealing, explicit trusted binding, predeclared unchanged quality targets,
fresh execution identity and separately recorded live decision/budget.

## Next dependency and scope

Human review is required by [architecture section 13](../../../docs/architecture/ARCHITECTURE.md#13-validation-and-release-evidence)
and [the contamination protocol](../../protocol.md#human-review-and-sealing).
Keep pending until an actual human decision arrives; corrections return to the
author and repeat mechanical validation. Once approved, retain this exact reviewed
revision and record the human decision before constructing its separate seal.
Then implement approved-revision binding with explicit known profiles, preserving
the original hard pin and refusing arbitrary replacement seals or paths. Validate
pending/wrong/replaced profiles, source mismatch, split isolation and label-free
workers before any new candidate/input/runtime refreeze. The original run must
remain visibly failed and cannot be resumed by replacing its configuration.

The request is for human label judgment only. It does not itself authorize a
new paid run or publication. Later dependency-gated V6 tasks remain open.
Resource observation remains 25.3 GiB free disk/40 percent free system memory;
only small text operations and one mechanical-check process. No services,
installs, private config/credential access, model downloads or background tasks.
Learning practice is unassessed. Optional exercise: explain why two valid byte
spans can still require a human to decide whether the sources conflict.
