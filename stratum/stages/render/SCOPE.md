# render - briefing artifact stage boundary

## Purpose

`stratum/stages/render` converts briefing markdown into template-backed HTML
and optional PDF artifacts.

The package entrypoint `stratum.stages.render` is the stable import surface for
artifact naming and render helpers.

## Modules

| File | Role |
|:---|:---|
| `__init__.py` | stable package surface for render helpers |
| `render.py` | stage CLI, markdown-to-HTML conversion, and PDF shell-out |
| `templates/` | built-in HTML templates used when callers do not provide one |
| `tests/` | render-stage unit tests |

## Boundaries

### Owns

- Build self-contained HTML from briefing markdown and template inputs.
- Produce stable artifact basenames for orchestrator path resolution.

### Does Not Own

- Does not decide briefing content or validation policy.
- Does not require Chrome to succeed at HTML rendering.
