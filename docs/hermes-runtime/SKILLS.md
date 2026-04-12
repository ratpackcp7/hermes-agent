# ~/.hermes/skills/ — Skills Inventory

Skills are reusable procedures loaded on-demand into agent sessions. Each skill is a directory under `~/.hermes/skills/<category>/<skill-name>/` containing a `SKILL.md` with YAML frontmatter and instructions.

## Skill Structure

```
~/.hermes/skills/
├── <category>/                # Grouping directory (e.g., devops, smart-home)
│   ├── <skill-name>/
│   │   ├── SKILL.md           # Skill definition (frontmatter + instructions)
│   │   ├── references/        # Optional reference docs
│   │   ├── templates/         # Optional templates
│   │   ├── scripts/           # Optional helper scripts
│   │   └── assets/            # Optional assets
│   └── ...
└── .bundled_manifest          # Cached manifest of all skills (auto-generated)
```

### SKILL.md Format

```yaml
---
name: skill-name
description: "What this skill does"
triggers: "comma, separated, trigger, words"
---

# Skill Title

Instructions here...
```

### How Skills Are Loaded

1. **Agent startup**: `.bundled_manifest` provides the skill list for system prompt injection
2. **Cron jobs**: `skills` field in `jobs.json` loads specific skills before execution
3. **Slash command**: `/skills` lets the user browse and load skills interactively
4. **Platform config**: `platform_toolsets` in config.yaml controls which toolsets (and their skills) are available per platform

Skills are injected as **user messages** (not system prompt) to preserve prompt caching.

## Adding a New Skill

1. Create directory: `~/.hermes/skills/<category>/<skill-name>/`
2. Create `SKILL.md` with frontmatter (name, description, triggers) and body (instructions)
3. The agent discovers it automatically on next session — no config change needed
4. To attach to a cron job, add the skill name to the job's `skills` array in `cron/jobs.json`

## Complete Skill Inventory (137 skills)

### apple (5) — macOS integrations
| Skill | Description |
|-------|-------------|
| apple-notes | Manage Apple Notes via memo CLI (create, view, search, edit) |
| apple-reminders | Manage Apple Reminders via remindctl CLI |
| findmy | Track Apple devices and AirTags via FindMy.app |
| imessage | Send/receive iMessages/SMS via imsg CLI |

### autonomous-ai-agents (7) — Agent orchestration
| Skill | Description |
|-------|-------------|
| cc-chain-orchestration | Auto-chain multi-phase cc-loop builds with escalation |
| cc-loop-delegation | Delegate tasks to cc-loop persistent Claude Code tmux session |
| claude-code | Delegate to Claude Code CLI agent |
| codex | Delegate to OpenAI Codex CLI agent |
| hermes-agent | Complete guide to using/extending Hermes Agent |
| opencode | Delegate to OpenCode CLI agent |

### creative (9) — Content generation
| Skill | Description |
|-------|-------------|
| ascii-art | ASCII art via pyfiglet (571 fonts), cowsay, image-to-ascii |
| ascii-video | ASCII art video production pipeline (MP4, GIF) |
| excalidraw | Hand-drawn style diagrams in .excalidraw format |
| image-generation | Image gen via Fal, OpenRouter, Pollinations |
| manim-video | Math/tech animations (3Blue1Brown style) |
| p5js | Interactive/generative visual art, WebGL |
| popular-web-designs | 54 production design systems |
| songwriting-and-ai-music | Songwriting + AI music generation |

### data-science (2)
| Skill | Description |
|-------|-------------|
| jupyter-live-kernel | Live Jupyter kernel for iterative Python |

### devops (24) — Infrastructure and operations
| Skill | Description |
|-------|-------------|
| docker-prometheus-grafana-monitoring | Prometheus + Grafana monitoring for Docker Compose |
| firecrawl-web-search-fix | Fix web_search hanging when Firecrawl is paused |
| gateway-platform-token-lock-fix | Fix stale token lock files after crashes |
| gateway-platform-troubleshooting | Debug gateway/workspace/dashboard connectivity |
| hermes-workspace-context-tracking | Architecture reference for session/token tracking |
| honcho-cleanup | Prune stale Honcho observations |
| honcho-troubleshooting | Troubleshoot Honcho self-hosted install |
| hybrid-cng-patching | Fix missing native modules in Expo CNG |
| nightly-retrospective | Nightly self-reflection + lesson persistence |
| openrouter-model-pricing | Look up OpenRouter model pricing |
| open-webui-terminal-setup | Connect Open Terminal to Open WebUI |
| postmortem-review | Structured postmortem from recent sessions |
| pre-update-conflict-check | Pre-flight check before upstream pulls |
| rclone-gdrive-rate-limit-fix | Fix rclone Google Drive API rate limiting |
| searxng-ddg-captcha-fix | Fix SearXNG DuckDuckGo CAPTCHA blocking |
| server-freeze-protection | Diagnose/fix server freezes (earlyoom, Docker limits) |
| solo-cleanup-sweep | Disk/state cleanup without sudo |
| systemd-user-timer-cleanup | Clean orphaned systemd user timers |
| token-usage-injection-patch | Inject live token usage into system prompt |
| update-hermes-agent-with-fork | Update hermes-agent with local fork commits |
| update-hermes-workspace | Update hermes-workspace (git pull, build, restart) |
| webhook-subscriptions | Create/manage webhook subscriptions |
| wiki-blog-ingest | Ingest blog posts into wiki |
| wiki-lint | Lint wiki for staleness, broken links, orphans |

### dogfood (3) — QA testing
| Skill | Description |
|-------|-------------|
| references | QA references |
| templates | QA templates |

### email (2)
| Skill | Description |
|-------|-------------|
| himalaya | CLI email via IMAP/SMTP |

### expo-react-native-unistyles-theme-fix (1)
| Skill | Description |
|-------|-------------|
| expo-react-native-unistyles-theme-fix | Fix black screen crashes with react-native-unistyles 3.x |

### expo-unistyles-theme-registration-fix (1)
| Skill | Description |
|-------|-------------|
| expo-unistyles-theme-registration-fix | Fix Unistyles theme registration |

### gaming (3)
| Skill | Description |
|-------|-------------|
| minecraft-modpack-server | Set up modded Minecraft from CurseForge/Modrinth |
| pokemon-player | Autonomous Pokemon play via headless emulation |

### github (7) — Git/GitHub workflows
| Skill | Description |
|-------|-------------|
| codebase-inspection | Codebase analysis (LOC, language breakdown) |
| github-auth | GitHub authentication setup |
| github-code-review | Review git diffs, leave PR comments |
| github-issues | Create/manage/triage GitHub issues |
| github-pr-workflow | Full PR lifecycle (branch, commit, merge) |
| github-repo-management | Clone/create/fork/configure repos |

### inference-sh (2)
| Skill | Description |
|-------|-------------|
| cli | Run 150+ AI apps via inference.sh CLI |

### leisure (1)
| Skill | Description |
|-------|-------------|
| find-nearby | Find nearby places via OpenStreetMap |

### mcp (3) — MCP server integration
| Skill | Description |
|-------|-------------|
| mcporter | MCP server CLI for ad-hoc interactions |
| native-mcp | Built-in MCP client for tool discovery |

### media (5)
| Skill | Description |
|-------|-------------|
| gif-search | Search/download GIFs from Tenor |
| heartmula | Run HeartMuLa music generation |
| songsee | Audio spectrogram/feature visualization |
| youtube-content | YouTube transcript extraction |

### mlops (10) — ML operations
| Skill | Description |
|-------|-------------|
| huggingface-hub | HF Hub CLI (search, download, upload) |
| (+ 9 category placeholder skills) | cloud, evaluation, inference, models, research, training, vector-databases |

### note-taking (2)
| Skill | Description |
|-------|-------------|
| obsidian | Read/search/create Obsidian notes |

### productivity (8)
| Skill | Description |
|-------|-------------|
| google-workspace | Gmail, Calendar, Drive, Sheets, Docs |
| handoff | Create/resume session handoffs |
| linear | Linear issues/projects via GraphQL |
| nano-pdf | Edit PDFs with natural language |
| notion | Notion API (pages, databases, blocks) |
| ocr-and-documents | Extract text from PDFs/scans |
| powerpoint | Create/edit/read .pptx presentations |

### react-native (1)
| Skill | Description |
|-------|-------------|
| expo-theme-registration-debug | Debug Unistyles "no theme selected" crashes |

### react-native-expo-debugging (1)
| Skill | Description |
|-------|-------------|
| react-native-expo-debugging | Debug black screens in React Native/Expo |

### red-teaming (1)
| Skill | Description |
|-------|-------------|
| godmode | Jailbreak API LLMs via G0DM0D3 techniques |

### research (10)
| Skill | Description |
|-------|-------------|
| arxiv | Search arXiv papers (free REST API) |
| blogwatcher | Monitor blogs/RSS feeds for updates |
| domain-intel | Passive domain reconnaissance |
| duckduckgo-search | Free web search via DDG |
| llm-wiki | Karpathy's LLM Wiki knowledge base |
| ml-paper-writing | Publication-ready ML/AI papers |
| parallel-cli | Parallel CLI for web search/extraction |
| polymarket | Polymarket prediction market data |
| research-paper-writing | End-to-end research paper pipeline |

### smart-home (13) — Home automation
| Skill | Description |
|-------|-------------|
| cp7-money-query | Query Chris's beancount financial data |
| empower-db-reconciliation | Reconcile Empower DB from beancount |
| empower-monthly-audit | Month-by-month Empower transaction audit |
| ha-addon-api-access | Access HA addon APIs remotely |
| ha-api-management | Create/manage HA entities via API |
| ha-cast-dashboard | Cast dashboards to Google Nest Hub |
| ha-energy-daily-calculation | Calculate daily energy from cumulative sensors |
| ha-sensor-charts | Generate charts from HA InfluxDB data |
| mfd-roster-query | Query MFD roster schedule |
| monitor-washing-machine | Monitor washing machine power usage |
| openhue | Control Philips Hue via CLI |
| tuya-localtuya-setup | Get Tuya local keys + configure LocalTuya |

### social-media (2)
| Skill | Description |
|-------|-------------|
| xitter | Interact with X/Twitter via x-cli |

### software-development (16)
| Skill | Description |
|-------|-------------|
| android-emulator-testing | Test Android APKs in Docker headless emulator |
| code-review | Code review guidelines |
| cp7-dashboard-development | Build/deploy CP7 Dashboard (Next.js) |
| cp7-mobile-development | Build/deploy CP7 Mobile (Expo/React Native) |
| deploy-docker-service-acerserver | Deploy Docker + Cloudflare tunnel |
| design-md-reskin | Reskin web app from DESIGN.md spec |
| expo-go-headless-setup | Expo Go on headless server |
| nextjs-hermes-chat-ui | Next.js chat UI for Hermes API |
| plan | Plan mode — write plans, don't execute |
| plan-resumption-check | Validate stale plans before executing |
| project-onboarding-audit | Audit projects and write AGENTS.md |
| requesting-code-review | Pre-commit verification pipeline |
| subagent-driven-development | Dispatch agents for independent tasks |
| systematic-debugging | 4-phase root cause investigation |
| test-driven-development | RED-GREEN-REFACTOR cycle |
| writing-plans | Create implementation plans from specs |

## Cron-Attached Skills

Skills that are automatically loaded before specific cron jobs run:

| Cron Job | Skills Loaded |
|----------|--------------|
| nightly-retrospective | nightly-retrospective |
| wiki-ingest | llm-wiki |
| wiki-monthly-prune | llm-wiki |
| Insurance spending monitor | empower-monthly-audit |
