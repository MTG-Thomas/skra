# Skra documentation guidance

These rules supplement the repository root AGENTS.md for documentation changes.

- Keep plans and implementation notes in their existing `docs/plans/` structure. Distinguish historical plans from implemented behavior; verify commands and API claims against current source.
- Link canonical setup, test, authentication, schema, and operational procedures instead of copying them into multiple agent files. Keep examples synthetic and exclude customer records, passwords, tokens, exports, and secret-store contents.
- Document org scoping, role enforcement, encryption/public-contract boundaries, migrations, and prerequisites where the changed feature depends on them. Preserve existing application safeguards.
- For test documentation, root `./test.sh` owns the isolated backend lane; frontend scripts and Playwright configuration own their respective lanes. State whether checks were executed or source-inspected. Never run a live tenant/database mutation as a documentation smoke check.
- Keep work on an isolated branch/worktree; summarize touched paths, evidence, and remaining gaps for review. Use existing issue context when supplied, without compulsory agent-specific labels, issue-claiming comments, standups, or shared-branch handoffs. Communicating or assigning work requires the request's authorization.
- Review links, code blocks, configuration names, and relevant rendered UI examples. Source validation is separate from release, deployment, or live data proof.
