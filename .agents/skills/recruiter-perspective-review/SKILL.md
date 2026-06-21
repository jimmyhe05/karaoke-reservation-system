---
name: recruiter-perspective-review
description: Evaluate a software portfolio project, repository, README, demo, project plan, or experience through the perspective of an internship recruiter and technical hiring team. Use to identify strongest signals, credibility gaps, resume-worthy work, interview depth, high-value improvements, or to draft truthful resume bullets from verified evidence. Use senior-pr-review for code defects and interview-explanation-mode for mock interview practice.
---

# Recruiter Perspective Review

Assess what a time-constrained reviewer can verify, what technical depth survives an interview, and what improvement most increases hiring signal.

## Trigger conditions

- Use for portfolio reviews, project positioning, hiring-signal prioritization, evidence gaps, or truthful resume bullet generation.
- Do not use for code correctness findings or live interview practice.

## Workflow

1. Identify target roles, candidate level, project purpose, and the evidence a reviewer can access.
2. Inspect the first-impression path: title, problem, demo, README, setup, architecture, code organization, tests, deployment, and recent history.
3. Separate visible claims from verifiable evidence.
4. Evaluate signals:
   - Product ownership and user understanding
   - Technical depth and tradeoff judgment
   - Code quality and maintainability
   - Testing and reliability
   - Security and production awareness
   - Documentation and communication
   - Measured outcome or evaluation
5. Identify commodity implementation, unexplained complexity, dead features, and credibility risks.
6. Rank improvements by hiring signal gained per unit of effort.
7. Extract defensible resume and interview themes. When bullets are requested, write concise action, technical decision, and outcome statements using only verified facts; use labeled metric placeholders when evidence is missing.
8. Recommend one flagship narrative and a small set of evidence artifacts.

## Evaluation standard

- Reward a coherent, working, well-explained system over a broad unfinished feature list.
- Look for one or two genuinely difficult engineering problems solved with evidence.
- Treat tests, metrics, evaluations, diagrams, runbooks, and demos as proof, not decoration.
- Value thoughtful constraints and tradeoffs more than fashionable tooling.
- Do not assume production users, scale, teamwork, or business impact from code alone.
- Tailor advice to internship expectations; avoid demanding staff-level infrastructure.

## Output contract

Return:

1. Ten-second recruiter impression
2. Strongest verified signals
3. Credibility or clarity gaps
4. Technical interview depth available
5. Prioritized improvements: quick win, medium investment, flagship differentiator
6. Resume-worthy themes and evidence needed
7. Suggested project narrative
8. Honest readiness assessment for target roles
9. Optional resume bullets with fact-check notes when requested

## Checklist

- Can a reviewer understand the problem and run or view the project quickly?
- Are the strongest technical claims backed by code, tests, metrics, or docs?
- Is the candidate's contribution clear?
- Does the project demonstrate judgment, not just framework familiarity?
- Is there a focused story rather than a tool and feature dump?
- Are recommendations realistic for the user's time and target level?
- Can the user defend every resume claim in a technical interview?

## Common mistakes

- Optimizing for buzzword count
- Suggesting many new features instead of finishing and measuring one
- Treating a polished README as a substitute for engineering evidence
- Recommending microservices or Kubernetes solely for resume appeal
- Inventing recruiter certainty or universal hiring preferences
- Writing resume bullets before identifying defensible impact
- Inventing users, scale, ownership, or metrics to strengthen a bullet

## Examples

Prompt:

> Assess my flagship full-stack project for backend internships.

Approach: inspect the first-impression path and repository evidence, identify the deepest backend signal, flag credibility gaps, and rank three improvements by hiring value.

Prompt:

> Which feature should I build next to make this AI project stronger?

Approach: evaluate existing proof, prefer evaluation, reliability, or user workflow depth over another demo feature, and explain what artifact would make the improvement verifiable.
