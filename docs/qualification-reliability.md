# Qualification reliability

Discovery and qualification are separate stages. Discovery stays broad and recall-first. It may return adjacent, incomplete, stale, or policy-sensitive leads. Qualification is a precision gate and must never treat a high keyword score as proof that a job is actionable.

## Decisions

- `strong`: actionable. The listing is explicitly open, the employer/business context is grounded, the title and work function directly align, seniority is aligned, at least 80% of extracted hard requirements have strong CV evidence, and salary/location/policy checks pass.
- `plausible`: interesting but not actionable. Typical reasons are adjacent function or domain, leadership stretch, unknown salary, or partial hard-requirement coverage.
- `insufficient_evidence`: the source lacks minimum evidence for responsibilities, requirements, employer context, role alignment, or an explicit open state.
- `policy_review`: business context is ambiguous under a configured exclusion and needs a person to decide.
- `stale`: expired, closed, removed, or HTTP 404/410. Explicit closure always beats Apply/Submit markers.
- `reject`: a confirmed policy/location/salary exclusion, material function/domain/seniority mismatch, critical hard gap, or less than half of hard requirements grounded.

Only `strong` is actionable. Unknown is not positive evidence. A numeric fit score may rank items inside a decision class, but it cannot upgrade a class or override a contradiction.

## Evidence coverage

A recommendation needs all of these categories:

1. Candidate requirements from the source.
2. Substantive responsibilities, not a title-only page.
3. Employer sector/business context, distinguishing an employer's own business from the industries its software serves.
4. Explicit liveness from the application route.
5. Role-title and work-function alignment.
6. Grounded hard-requirement coverage against bounded CV facts.
7. Configured policy, location, and salary outcomes.

The model is profession-neutral. Profession-specific vocabulary belongs in configuration or evidence adapters, not in the decision ladder.

## Benchmarking

`tests/fixtures/trials_1_5_qualification.json` is the offline labeled benchmark derived from saved staging Trials 1-5. Run it with:

```bash
python -m findmejob.benchmark tests/fixtures/trials_1_5_qualification.json
```

Report actionable precision and recall as exact numerators/denominators, full decision accuracy, mismatches, and zero-tolerance failures. The fixture is a regression set, not proof of general reliability. New staging trials must use new broad discovery inputs. Do not tune labels after seeing model output without recording why the independent label changed.
