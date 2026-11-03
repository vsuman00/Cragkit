# Reviewed packet profiles EPR-r1

V6-02I2 follows the user's explicit approval, "I approved", of the unchanged
six recovery questions/eight facets on 3 November 2026. The separate approval
record links the pre-approval revision, and the nine-file seal records source,
labels and review metadata. The original review seal and failed run remain intact.

For example, changing a mutable manifest and its adjacent seal must still fail:
the selected seal's digest is independently pinned in source.

## Profiles and selection

Root owns `tools/evaluation_profiles.py`, this contract, approval/seal data,
tracker, parent integration, final tests and Git. The helper is frozen before
peer implementation. Only `original-r1` and `recovery-r1` are known; the optional
configuration field `evaluation_revision` defaults to the original profile for
existing configuration compatibility. Unknown/non-string revisions fail closed.
No caller-selected seal, manifest, source prefix or label path is accepted.

`packet_profile(configuration, *, split='held_out')` returns the immutable known
`PacketProfile` path/digest record. Development always uses the original approved
development corpus; held-out uses the selected known profile. `input_limits`
returns a new bounded path/limit mapping: the original six preregistration inputs,
plus recovery manifest/seal only when recovery is selected. Held-out label bytes
are not a preregistration input read. No helper import performs I/O.

Original seal SHA256 remains
`210ddce9237847d271db35dbff1d7c74a1ba1f30323a3f4119f939a604a83f81`.
Recovery seal SHA256 is
`46a7e1bba338ff205d6d5e49f45a61db9cca3f0c8acb81b9c70d51870fd5e195`.
Root alone may change these pins after a genuine reviewed revision and recorded
approval. Tests use isolated synthetic identities, never edit actual seals or
assert unseen quality from a fake run.

## Bounded lanes

I2b Sol binder owns `tools/evaluation_packet.py` and its test file. I2c Sol checker
owns `tools/check_release_readiness.py` and its test file, and assembles both.
Root I3 owns `tools/run_release_evaluation.py` and its tests after binder API
handoff, then candidate/input/runtime refreeze. Peers coordinate directly and
return ownership before root integration. No concurrent tracker/shared-helper
edits. Escalate protected/outcome changes to root, unresolved decisions to Astra.
One root-owned test process; no peer services, installs, credentials or live calls.

The binder retains its original seal constant alias for legacy synthetic test
injection; real original approval still uses that unchanged fixed value. For the
recovery held-out profile it uses the new independently pinned digest. Source/
compiled identity gating remains unchanged and must precede decoding held-out
labels. Check settings, exact bounded preregistration inputs, original approval
and selected approval, selected manifest/source/label digest agreement, scope,
immutable revisions and native packet schema. Wrong/replaced/pending approval,
unknown profile, source drift or unsafe path fails with fixed diagnostics.

The private issued bound snapshot additionally records the selected known label
path/profile. Expose `reviewed_questions(root)` to load only that snapshot's
pinned approved questions for independent parent scoring after native execution.
It must refuse unissued objects, changed label bytes and unapproved state.
Keep labels/facets out of runtime packets. Existing provenance fields remain;
add `packet_revision` and `labels_path` so saved runs disclose selected input.
Returned runtime/scoring copies cannot mutate the private issued binding.

The checker validates selected profile metadata and original/recovery seals
without opening either held-out question file. Original approval remains a
prerequisite for original development inputs. Exact path inventories, independent
seal pins and source/label digest provenance remain distinct from human judgment.
Synthetic tests cover both valid profiles and malformed/unknown/path-swapped/
replaced/pending approvals. Real original development checks keep their existing
nine documents/24 queries. Recovery tests use synthetic copies, not actual
approved held-out labels, for routine runtime interpretation.

The active candidate is not rewritten during implementation. After verification,
root preserves the original candidate as history, selects the approved recovery
profile with unchanged quality/resource/call/spend targets, refreezes source and
builds a fresh verified runtime. That is a new evaluation identity; never delete
or reuse the old admission or turn the failed unsealed tape into success. Live
execution and publication remain separate from this binding acceptance.
