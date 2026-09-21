# Research framing and proposed protocol

Status: proposed research protocol, not an implemented experiment runner.

## Relationship to Che

Che (1993) studies procurement offers containing quality and price, ranked by an announced scoring rule. His model distinguishes the buyer's utility from the rule used to award the contract. Our implementation borrows multidimensional scoring, but lacks strategic price/quality choices, delivery costs, equilibrium bidding, and contract/payment rules. Its hidden selector is an additional modeling choice, not a replication of Che.

Source: [Che, Design Competition through Multidimensional Auctions](https://www.columbia.edu/~yc2271/files/papers/Scoring%20auctions.pdf).

## Operational model

Separate immutable applicant qualifications, the feasible offer (scope, delivery time, requested resources), and presentation (evidence choice, structure, wording). A writing policy changes presentation; it cannot invent qualifications. Changes to an offer require explicit feasibility and reservation checks.

Represent an environment as preferences, allocation rule, rival population, capacity, and arrival process. Preserve uncertainty over these separately. The current weighted score and ranking engine is one environment family. Thresholds, vetoes, rolling selection, and cohort complementarity require distinct mechanisms; they are not merely new weight vectors.

Public context provides hypotheses about environments, not known probabilities. Winner-only profiles are selected observations: they cannot identify the applicant population, rejection threshold, or true preference weights. With binary feedback, several mechanisms may explain the same outcomes. Maintain competing hypotheses and sensitivity analyses rather than claiming identification.

The current rivals are sampled feature vectors, not strategic players. Introduce strategic rivals only after a stationary benchmark works: each rival chooses a feasible offer/presentation to maximize its own outcome. Freeze opponents within evaluation epochs. An adaptive league does not establish equilibrium.

## First scientific question

Under a fixed model-call budget, does binary-feedback prompt-policy search improve fresh submissions on held-out opportunities relative to fixed drafting and equally budgeted random strategy search?

This evaluates a learning procedure, not the best saved document. Initially call this contextual strategy optimization with bandit feedback. Sequential research, revision, and submit-time actions would justify a richer sequential decision model.

## Experimental design

1. Choose one domain first, such as research fellowships. Assemble consented or synthetic applicant dossiers and opportunities. Split by institution/opportunity family before tuning; near-duplicate postings must not cross splits.
2. Freeze a versioned benchmark: source snapshots, applicant facts, selection families, rival generators, generation/judging settings, budgets, seeds, and primary endpoint. Synthetic priors remain declared assumptions.
3. Compare fixed drafting, equal-budget random search, binary-feedback adaptive search, and an explicitly privileged full-feedback diagnostic baseline. Give operational methods identical evidence and resource budgets. Account for proposal, writing, and evaluation calls separately.
4. Tune on training opportunities. Select policies on a validation partition. Evaluate frozen policies once on untouched test opportunities and fresh generated documents. Test results never enter learner histories or further policy selection.
5. Use matched competitor pools and scenario seeds for each method, with independent generation repeats. Vary judge seeds or independent reviewers separately. The existing twelve worlds reuse one document judgment and are not twelve independent judgments.
6. Primary endpoint: per-opportunity held-out acceptance fraction, averaged equally across opportunities. Report paired method differences and uncertainty clustered by opportunity (or institution when dependent). Do not treat every correlated world decision as an independent sample.
7. Secondary endpoints: performance by mechanism, lower-tail robustness, factual support, feasible commitments, human-rated writing specificity, model calls, tokens, latency, and cost per improvement. Estimate actual cost rather than assuming equal calls imply equal cost.
8. Run a pilot to estimate between-opportunity variance and within-opportunity correlation; use these to plan sample size for a predeclared meaningful effect. Label a small pilot exploratory, not confirmatory.

## Ablations and falsification

- Feedback: none, shuffled binary feedback, actual binary feedback, privileged detailed feedback. If shuffled feedback performs similarly, gains may come from extra sampling rather than learning.
- Optimizer: refinement only, exploration only, branching, and merging, with matched budgets.
- Selector: known announced scoring benchmark versus hidden scoring; fixed versus uncertain weights; held-out mechanism families.
- Rival model: frozen archetypes versus independently generated populations, then strategic adaptation in a separate study.
- Judge: same-model assessment versus independently blinded human or different-model assessment. Randomize presentation order and conceal generating method.
- Voice criterion: compare operational preferences against blinded human judgments of specificity, clarity, and naturalness. Do not interpret style ratings as AI-authorship detection. Research ablations should not silently disable production quality gates.

## Che-style benchmark before realism

Add a separate synthetic procurement environment with explicit quality q, price p, private delivery-cost type, announced score S(q,p)=s(q)-p, feasible action bounds, and defined winner payments. Implement the first-score case first: the winner delivers its offered quality at its offered price. Verify allocation and payoff accounting, then compare policy search against a numerical best-response benchmark for a specified rival distribution. Regret is relative to that benchmark, not an asserted equilibrium.

Only afterward hide scoring parameters, replace scalar quality with multiple attributes, add noisy document assessment, and introduce deadlines. This sequence isolates whether failures arise from optimization, incomplete information, language measurement, or market assumptions. Fixed-award fellowships need an allocation-contest model rather than an artificial price bid.

## Records needed next

Add experiment ID, split, method assignment, opportunity family, budget ledger, generation seed, judge replicate, selection-model version, rival seed, policy version, intervention label, and promotion decision. Existing immutable policies, inputs, outputs, judgments, and trials provide much of the audit foundation. Holdout enforcement, independent judging, experiment scheduling, and champion promotion still need implementation.

Keep a vector of performance by mechanism. Promote a champion only within a declared domain and protocol using validation results. Preserve specialists. A single aggregate score cannot represent every tradeoff.

## Scope of conclusions

Simulation results support claims about the stated benchmark. Evidence of real-world benefit requires a separate prospective evaluation with independent outcomes and appropriate assignment. Do not submit duplicate applications as experimental treatments. Winning must also satisfy the applicant's reservation conditions; acceptance alone is not applicant welfare.
