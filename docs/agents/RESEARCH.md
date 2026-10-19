# Why Cragkit has AGENTS.md

Researched 19 October 2026 using the format's official site and official Codex guidance.

`AGENTS.md` is a Markdown convention for persistent repository instructions. Common content includes project context, setup/test commands, conventions and security boundaries. Nested files can supply local instructions, with behavior depending on the coding tool. The conventional filename is plural, so this project uses one root `AGENTS.md` rather than competing copies named `AGENT.md` or `agent slot.md`. [Official format guidance](https://agents.md/).

Codex documents discovery of agent instruction files and scoped instruction overrides. When diagnosing loading, inspect the active tool's discovery rules rather than assuming every agent handles files identically. [Official Codex guidance](https://developers.openai.com/codex/guides/agents-md/).

For Cragkit, the root file emphasizes the decisions most likely to be lost across sessions: native Python/TypeScript libraries, architecture-first task selection, evidence integrity, access constraints, modest local resource use, learning support and honest verification. Detailed architecture and task lists remain linked rather than copied into the instructions.

Commands are intentionally not invented while package manifests are absent. V0 will establish verified commands and record them in the development guide. Multi-agent ownership and handoffs are a project-specific protocol in [WORKFLOW.md](WORKFLOW.md); they are not a feature enforced by the Markdown format.

The file can reduce repeated explanations and make expectations inspectable. It cannot guarantee instruction compliance, prevent hallucination, enforce permissions, lock files or replace tests. Its effectiveness must be checked through actual agent behavior and updated when the project changes.
