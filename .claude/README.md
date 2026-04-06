# Claude Configuration for Gap Analysis

This directory contains Claude Code configuration for orchestrating changes in the gap analysis repository.

## Problem Statement

When gap analysis scripts are added, updated, or removed, multiple related files must be kept in sync:
- Script files (`scripts/gap-*.py`)
- Templates (`scripts/templates/*.j2`)
- Orchestrator (`scripts/gap-all.sh`)
- Report aggregator (`scripts/generate-combined-report.py`)
- Skills (`skills/*-gap/SKILL.md`)
- Documentation (`docs/*.md`, `README.md`)
- CLAUDE.md

**Pain Point**: Manually tracking and updating all these dependencies is error-prone and time-consuming.

## Solution

Automated orchestration using Claude Code:

### 1. Rules (`.claude/rules/`)

**All rules follow consistent workflow:** Show plan → Suggest subagents → **Ask for approval** → Spawn after "yes"

**`when-to-plan.md`** - **CRITICAL** Decision matrix for impact-based planning:
- High-Impact vs Low-Impact change classification
- When to show implementation plans
- When to proceed directly without planning
- Rule precedence hierarchy
- Decision tree diagram
- Edge case guidelines
- Examples for each category

**`command-execution-permissions.md`** - **NEW** Defines when to ask for approval vs proceed:
- Read-only commands (ls, grep, cat) → Proceed directly
- Modification commands → Ask for approval
- Git operations → Always ask for approval
- File creation/deletion → Ask for approval
- Installing dependencies → Ask for approval
- Temp directory operations → Proceed directly
- Validation/testing → Automatic (per cleanup-analyzer)

**`gap-script-orchestration.md`** - Defines the complete dependency matrix and rules for:
- Adding new gap scripts (WHAT needs updating)
- Updating existing scripts
- Removing scripts
- Standard templates and patterns
- Pre-commit validation checklist
- References when-to-plan.md for HOW to get approval

**`proactive-agent-usage.md`** - Rules for when Claude should suggest subagents:
- When to suggest (ALWAYS ask for approval first)
- Suggestion patterns and phrasing
- Getting user approval before invoking
- Quality assurance responsibility
- Integration with hooks (ask approval even for hook-detected issues)

**`proactive-cleanup-suggestions.md`** - Triggers for suggesting cleanup:
- CLAUDE.md ≥300 lines OR change adds ≥500 lines
- Ask approval before running cleanup-analyzer
- Testing guarantees (baseline + post-cleanup validation)

### 2. Subagents (`.claude/subagents/`)

Auto-trigger on file changes to orchestrate related updates:

**`gap-script-orchestrator.md`** - Primary orchestrator
- Triggers on: `scripts/gap-*.py` changes
- Actions: Creates templates, updates gap-all.sh, creates skills, updates docs
- Output: Comprehensive change report

**`docs-reviewer.md`** - Documentation synchronizer
- Triggers on: Script and lib file changes
- Actions: Updates docs/*, README.md with current info
- Output: Documentation discrepancy report

**`skills-reviewer.md`** - Skills synchronizer
- Triggers on: Script changes
- Actions: Creates/updates skills/*.md files
- Output: Skill coverage report

**`claude-md-updater.md`** - CLAUDE.md maintainer
- Triggers on: Script, lib, orchestrator, container changes
- Actions: Updates CLAUDE.md while keeping it concise (<200 lines)
- Output: Minimal diff report

### 3. Hooks (`.claude/hooks/`)

**`pre-commit`** - Manual validation script (can be installed as git hook)
- Validates Python and Bash syntax
- Checks gap script completeness (templates, skills)
- Validates gap-all.sh orchestration
- Checks documentation sync
- Prevents committing reports/
- Validates import patterns
- Checks Jinja2 templates

**Note:** To use as a git hook, install it:
```bash
ln -sf ../../.claude/hooks/pre-commit .git/hooks/pre-commit
```

### 4. Settings (`.claude/settings.json`)

Minimal configuration for:
- Default model (Sonnet)
- Auto-memory enabled

**Note:** Subagent triggering is controlled by the **rules files** (when-to-plan.md, proactive-agent-usage.md), not by settings.json. Claude reads these rules and decides when to suggest/invoke subagents based on the context.

## Workflows

### Adding a New Gap Script

**You do:**
1. Tell Claude: "I want to add a network gap analysis script"

**Claude does (following when-to-plan.md):**
1. ✅ Recognizes this as **high-impact** change
2. ✅ Shows implementation plan listing all affected files
3. ✅ Suggests: "gap-script-orchestrator can scaffold this. Invoke it?"
4. ✅ Waits for your approval

**You approve:**
5. Say "proceed" or "yes"

**Claude then:**
6. ✅ Invokes `gap-script-orchestrator` subagent
7. ✅ Creates templates, updates gap-all.sh, creates skill, updates docs
8. ✅ Provides comprehensive change report

**You commit:**
9. ✅ `pre-commit` hook validates (if installed) or run `.claude/hooks/pre-commit` manually

### Updating an Existing Gap Script

**Scenario A: High-Impact (validation logic change)**

**You do:**
1. Tell Claude: "I'm adding CHECK #2 to gap-aws-sts.py"

**Claude does:**
1. ✅ Recognizes this as **high-impact** (affects output, docs, skills)
2. ✅ Shows plan listing affected files
3. ✅ Suggests: "skills-reviewer and docs-reviewer can help. Invoke them?"
4. ✅ Waits for approval, then invokes after "yes"

**Scenario B: Low-Impact (bug fix, refactoring)**

**You do:**
1. Tell Claude: "Fix the URL validation in ack_validation.py"

**Claude does:**
1. ✅ Recognizes this as **low-impact** (internal only)
2. ✅ Makes change directly
3. ✅ Brief explanation, no plan needed

### Removing a Gap Script

**You do:**
1. Tell Claude: "I want to remove gap-old.py"

**Claude does:**
1. ✅ Recognizes this as **high-impact** change
2. ✅ Shows plan listing files to remove
3. ✅ Suggests gap-script-orchestrator
4. ✅ Waits for approval
5. ✅ After "yes", invokes subagent to remove files and update docs
6. ✅ Asks for confirmation before deleting files

## File Structure

```
.claude/
├── README.md                              # This file
├── settings.json                          # Claude configuration
├── rules/
│   ├── when-to-plan.md                   # Impact classification
│   ├── command-execution-permissions.md  # Command approval rules
│   ├── gap-script-orchestration.md       # Dependency matrix and rules
│   ├── proactive-agent-usage.md          # Subagent suggestion rules
│   └── proactive-cleanup-suggestions.md  # Cleanup triggers
├── subagents/
│   ├── gap-script-orchestrator.md        # Primary orchestrator
│   ├── docs-reviewer.md                  # Documentation sync
│   ├── skills-reviewer.md                # Skills sync
│   ├── claude-md-updater.md              # CLAUDE.md sync
│   └── cleanup-analyzer.md               # Cleanup orchestration
└── hooks/
    └── pre-commit                         # Validation script (optional git hook)
```

## Benefits

✅ **Consistency**: All related files stay in sync automatically; all rules follow the same approval workflow
✅ **User Control**: Claude always asks for approval before spawning subagents (no surprises)
✅ **Speed**: No manual tracking of dependencies
✅ **Quality**: Pre-commit validation script catches issues early
✅ **Documentation**: Always up-to-date
✅ **Transparency**: Decision tree and rule precedence make workflow clear
✅ **Less Mental Overhead**: Focus on script logic, not orchestration

## Testing the Configuration

### Test New Script Workflow

```bash
# Create a test script
cat > scripts/gap-test.py << 'EOF'
#!/usr/bin/env python3
"""Test Gap Analysis - For testing orchestration."""
# ... minimal implementation ...
EOF

# Ask Claude to orchestrate
claude "I added scripts/gap-test.py, please orchestrate related changes"

# Claude should:
# 1. Detect high-impact change (when-to-plan.md)
# 2. Show implementation plan
# 3. Suggest gap-script-orchestrator
# 4. After approval, create templates
# 5. Update gap-all.sh
# 6. Create skill
# 7. Update docs
# 8. Show comprehensive report
```

### Test Pre-commit Hook

```bash
# Test syntax validation
echo "syntax error" > scripts/test-bad.py
git add scripts/test-bad.py
git commit -m "test: bad syntax"
# Should fail with syntax error

# Test report prevention
touch reports/test-report.md
git add reports/test-report.md
git commit -m "test: prevent reports"
# Should fail with warning
```

## Customization

### Change Default Model

In `.claude/settings.json`:
```json
{
  "defaultModel": "opus"
}
```

### Disable Auto-Memory

```json
{
  "autoMemory": false
}
```

### Add Custom Rules

Create new rule file in `.claude/rules/` and reference in `settings.json`.

## Troubleshooting

**Subagents not being suggested:**
- Verify `.claude/rules/*.md` files are present
- Check that changes match trigger patterns in `proactive-agent-usage.md`
- Ensure impact classification (high vs low) is correct per `when-to-plan.md`

**Pre-commit hook not running:**
- By default, the hook is NOT installed (it's a manual validation script)
- To install: `ln -sf ../../.claude/hooks/pre-commit .git/hooks/pre-commit`
- Verify it's executable: `chmod +x .git/hooks/pre-commit`
- Test manually: `.claude/hooks/pre-commit`

**False positives in validation:**
- Review `.claude/rules/gap-script-orchestration.md`
- Adjust validation logic in pre-commit hook
- Set `strictMode: false` for warnings instead of errors

## Future Enhancements

Potential additions:
- MCP server for GitHub API integration
- Auto-create PRs for managed-cluster-config updates
- Memory seeds for common patterns
- CI/CD integration for auto-validation
