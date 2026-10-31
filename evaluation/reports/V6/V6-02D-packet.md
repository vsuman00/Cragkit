# Sealed evaluation packet binding

State: V6-02D4 COMPLETE for packet binding. Genuine-provider execution, exact candidate preparation and V6 release acceptance remain open.

For example, a replacement source must not become approved merely because someone updates its local manifest checksum. The binder pins the original human-review seal independently of the candidate file, and requires both records to identify the same bytes consumed by parsing.

Root kept the dependent reader/projection/source-gate work in one writer lane. A Sol reviewer inspected the boundary separately and reported concrete fixes. The [EPB-r1 contract](../../../contracts/EVALUATION_PACKET_BINDING_V6.md) describes the resulting API and limits. Implementation is `tools/evaluation_packet.py`; its focused regressions are `tools/tests/test_evaluation_packet.py`.

The binder projects only EVX-r1 documents and query/scope/filter fields. Reviewed support, answerability and facets remain outside the workers. Returned packets are fresh copies of a privately issued immutable snapshot. Provenance cannot be supplied through a manually constructed snapshot, and always marks compiled artifacts unverified. The snapshot does not itself authorize HTTP or discover keys.

Review found and root fixed FIFO blocking before file-type validation, inherited unbounded configuration reads, decoder exception context, malformed nested settings and a second-read mismatch between preregistration and consumed data. File reads now use directory descriptors, reject symlinks/nonregular files without following them, enforce byte ceilings and retain the exact verified bytes for parsing. The source decoder and JSON parser return fixed errors without retaining private parser exceptions. Updating mutable candidate/seal records together cannot replace the original approval pin.

The release checker now exposes pure `check_settings` validation. Its CLI still performs the complete digest, coverage and evidence-path checks. Binding uses the pure settings helper and its own bounded readers; contradictory provider profiles are rejected before execution. Frozen models, targets, corpus and request/spend limits were not changed.

Held-out interpretation requires explicit selection plus clean matching Git source and Python/binder import origins. Tests prove that a rejected source gate does not decode the held-out dataset. Positive held-out unit tests use a synthetic packet and test-only approval pin, never the original held-out labels. Source proof is separate from compiled Node or installed-artifact proof.

## Actual evidence

The focused binding/release-checker suite passed 34 tests (27 binding cases); the complete Python/tool suite passed 3,460 with four intentional malformed-model serializer warnings. Tests cover label exclusion, immutable copies/issuance, candidate/approval drift, changed files between verification and parsing, one read per consumed preregistration file, malformed/nonfinite JSON, FIFO/symlink/directory/size refusal, invalid UTF-8 without retained context, provider-profile mismatch and real temporary Git repositories with clean, dirty, untracked and wrong-tree cases.

A real development binding loaded all nine approved development documents and 24 queries. The runtime packet SHA-256 is `3b306b4654c7044e95345644ea3ceb1aacd678e21cbdfce036ba19b12b2854de`. An instrumented metadata-only probe then requested original held-out binding: the current stale candidate source was rejected with `evaluation_candidate_source_mismatch`, and the original held-out JSON was not interpreted. Neither this refusal nor development projection establishes live evaluation acceptance.

The full release configuration checker still verified six digests and 10 requirement / 105 edge paths; the seal checker verified all 16 inputs. Commands, complete-suite results and evidence hashes are in [the verification record](V6-02D-packet-verification.json). No database, provider, credential, model installation, hosted write, CI or package publication was used for D4. Suites ran serially; temporary Git processes closed. Final headroom was 30 GiB disk and 44 percent system memory free. The native five-mode checkpoint remains separately documented in [execution evidence](V6-02D-execution.md).

Next: prepare a clean candidate checkout without overwriting the user's existing edits, bind compiled/runtime artifacts, finish secure provider configuration and record/replay the genuine held-out comparison. All later V6 gates remain required. Learning practice is unassessed; an optional exercise is to explain why matching a source tree does not prove that an ignored `dist/` directory was built from it.
