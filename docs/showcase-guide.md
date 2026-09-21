# Showing Submission Standout

[Public interactive tour](https://puedesleerlo.github.io/submission_standout/) · [Source](https://github.com/puedesleerlo/submission_standout)

## A recruiter: a two-minute product story

Open the recruiter view. Start with the problem: a generic writing assistant can polish a letter without establishing that its strategy fits a particular opportunity. Show the evidence, the explicit writing policy, and the resulting draft. Switch the feedback example between learner and researcher views to explain why the application is more than a chat interface.

Suggested introduction: “I built a workbench that turns applicant evidence into tailored submissions and tests competing writing strategies under uncertain selection rules. It keeps every policy and draft traceable, then checks whether improvements transfer to unseen opportunities.”

Point to observable engineering work: scoped LLM roles, background jobs, immutable records, an editable document workflow, tested feedback boundaries, and a controlled experiment runner. Describe what you implemented and the tradeoffs you chose. Do not present synthetic win rates as improved hiring outcomes.

## A technical counterpart: an eight-minute investigation

Start with the research question: does binary feedback improve transfer beyond equally budgeted exploration? Open the technical tour's architecture. Then open Research study locally and inspect the three partitions, five methods, budget allowance, and frozen policy manifest.

Explain the experimental unit. A document receives one Kimi judgment reused across twelve matched worlds. Fresh draft generations are replicates within an opportunity. The uncertainty estimate clusters by opportunity family, rather than pretending world decisions are independent data.

Open the blinded human-review workspace in a separate tab. Show that the reviewer receives text and evidence, while methods and model scores are absent. Export a fictional study to inspect the exact learner inputs, shuffled labels, protocol hashes, policy selection, allocation worlds, and token ledger.

Discuss the limits directly: incomplete information does not identify the true selector; synthetic competitors are not equilibrium players; equal call ceilings are not equal dollar costs; the local process is trusted; one reviewer does not establish inter-rater reliability; and prompt search does not update neural weights.

## Demo preparation

The public tour makes no model calls and includes explicitly illustrative content. The local fictional pilot starts empty and runs only when requested. Full stages are paid operations with visible ceilings; use a completed fictional study for a live presentation rather than making an audience wait for generation. Tests use a deterministic fake provider solely to verify behavior and must not be presented as scientific results.

For scientific evidence, collect independent opportunities, group related institutions before splitting, predeclare the meaningful effect and budget, and recruit an independent human reviewer. Preserve disappointing and null results. A credible demonstration can show that the controls work before there is evidence of improved selection outcomes.
