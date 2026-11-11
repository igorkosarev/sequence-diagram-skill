# sequence-diagram — a Claude skill

A [Claude skill](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview) that turns a described interaction flow into a readable **PlantUML** sequence diagram:

- participants grouped into colored boxes by system/domain;
- actor / participant / database stereotypes and activation bars;
- semantically colored `alt` / `opt` / `loop` / `break` blocks for branches and errors.

Works from prose, bullet steps, or a rough sketch of who calls whom. Triggers in English and Russian ("sequence diagram", "диаграмма последовательности", "нарисуй флоу"…).

## Contents

| Path | Purpose |
|---|---|
| `SKILL.md` | Instructions Claude follows |
| `assets/template.puml` | Starting template with the color palette |
| `references/` | PlantUML sequence cheatsheet and palette preview |
| `scripts/validate_puml.py` | Checks a generated `.puml` before it is shown |

## Install

**Claude Code** — clone into your skills folder:

```bash
git clone https://github.com/igorkosarev/sequence-diagram-skill ~/.claude/skills/sequence-diagram
```

(or into `.claude/skills/sequence-diagram` inside a project to scope it to that project).

**Claude apps (claude.ai / desktop)** — download the repo as ZIP and upload it in Settings → Capabilities → Skills.

## License

MIT
