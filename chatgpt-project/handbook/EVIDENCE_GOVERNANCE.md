# Evidence governance

Use this policy in every generated workspace. Keep claims atomic enough that a reviewer can verify one material proposition without silently accepting another.

## Claim states

- **Grounded fact**: directly supported by a current primary source or direct observation.
- **Corroborated**: supported by at least two independent credible sources, with no material contradiction.
- **Experimental**: observed in a recorded test but not yet established as broadly repeatable.
- **Looks believable**: plausible and partially supported, but missing decisive evidence.
- **Overstated**: the source evidence supports a narrower claim than the wording implies.
- **Forecast/opinion**: a prediction, interpretation, or recommendation rather than an observed fact.
- **Contradicted**: credible evidence materially conflicts with the claim.
- **Stale**: evidence is outside its refresh window or the underlying surface changed.
- **Unknown**: evidence is absent or too weak to classify.

Do not use confidence language as a substitute for a state. Split mixed claims whenever their material parts would receive different states.

## Source tiers

- **A — direct/primary**: runtime observation, official documentation, regulation, filing, dataset, paper, or reproducible artifact.
- **B — close primary**: named builder, researcher, operator, or organization reporting work they directly performed.
- **C — rigorous secondary**: transparent synthesis with traceable citations and methods.
- **D — informed commentary**: useful interpretation with limited underlying evidence.
- **E — promotional or anonymous**: weakly attributable, incentive-heavy, or non-verifiable material.

Tier measures evidence proximity, not whether a person is generally trustworthy. A source can be Tier B for its own work and Tier D for claims outside its knowledge.

## Fact-check loop

1. Write the decision-relevant claim in falsifiable language.
2. Record scope, date, target surface, and what would change the decision.
3. Find the closest primary evidence and exact supporting location.
4. Search deliberately for contradiction, boundary conditions, and missing populations.
5. Separate observation from interpretation and forecast.
6. Assign state, confidence, freshness, owner, and refresh trigger.
7. Link the claim to the decision or experiment that consumes it.
8. Recheck before a consequential decision, after a source correction, or when the surface changes.

## Source reliability scorecards

Score a source only for a defined **source x domain x claim type x time window**. Do not publish a universal personality score.

- Fewer than 10 resolved claims: **Unrated**.
- 10–24 resolved claims: **Provisional**; report high uncertainty.
- 25 or more resolved claims from a predeclared corpus: **Established**, while still showing the sample and window.

Score resolved claims on accuracy, traceability, calibration, and correction hygiene. Mark dimensions `N/A` when evidence is insufficient; never convert missing evidence into a zero. Record disclosed affiliations and incentives separately from accuracy. Do not infer hidden motives as facts.

## Freshness defaults

| Evidence | Default review trigger |
|---|---|
| Active model/product surface | Release, access, or behavior change; otherwise 14 days |
| Fast-moving technique | Material new evidence; otherwise 30 days |
| Market or competitor condition | Before the decision; otherwise 30–90 days |
| Law, policy, safety, or contract | Before use and whenever jurisdiction or policy changes |
| Stable concept or historical fact | On contradiction or annual review |

Replace defaults when the decision has a shorter evidence half-life.
