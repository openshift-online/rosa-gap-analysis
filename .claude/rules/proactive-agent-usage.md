# Proactive Agent Usage Rules

Instructions for when Claude should suggest and offer to invoke subagents.

## Core Principle

In this gap analysis repository, **subagents are powerful quality assurance tools** that help orchestrate complex changes. When specific conditions are met, you should **suggest relevant subagents and ask permission** before invoking them.

**ALWAYS ask for approval** before spawning any subagent. No exceptions.

## Prerequisites

Read these rules first:
- `.claude/rules/when-to-plan.md` - Impact classification and decision tree
- `.claude/rules/gap-script-orchestration.md` - What needs updating for gap scripts

Before using subagents, check `.claude/rules/when-to-plan.md` to determine if this is a high-impact or low-impact change. Only high-impact changes typically need subagent assistance.

## Subagent Suggestion Matrix

When these conditions are detected, **suggest** the appropriate subagent(s):

| Condition Detected | Suggested Subagent(s) | When to Suggest |
|-------------------|---------------------|---------------|
| `scripts/gap-*.py` created/deleted | gap-script-orchestrator | After showing implementation plan |
| `scripts/gap-*.py` modified (high-impact) | gap-script-orchestrator | If validation logic or output changes |
| User asks to "add gap script" | gap-script-orchestrator | After showing plan |
| User mentions "orchestrate" | gap-script-orchestrator | Immediately |
| **`scripts/lib/ack_validation.py` modified** | **gap-script-orchestrator** | **If result structure changes (new fields like `warnings`, changed return values)** |
| **`scripts/lib/*.py` adds/removes fields in results** | **gap-script-orchestrator** | **When return structure changes affect templates** |
| **`scripts/gap-*.py` adds new comparison categories** | **gap-script-orchestrator** | **When new fields added to comparison dict (e.g., `continues_default_hypershift`)** |
| Documentation looks outdated vs code | docs-reviewer | When inconsistency detected |
| Skills look outdated vs code | skills-reviewer | When inconsistency detected |
| CLAUDE.md needs sync | claude-md-updater | When changes affect architecture |
| CLAUDE.md ≥300 lines OR change adds ≥500 lines | cleanup-analyzer | After change completes successfully |
| User says "proceed" after plan | Subagents mentioned in plan | After explicit approval |

## Invocation Patterns

### Pattern 1: High-Impact Change - Show Plan First

**User:** "I just added scripts/gap-network.py"

**Your Response:**
```
## Implementation Plan

This is a high-impact change affecting multiple areas.

### Files to Create:
1. scripts/gap-network.py
2. scripts/templates/network.{md,html}.j2
3. skills/network-gap/SKILL.md

### Files to Update:
1. scripts/gap-all.sh
2. scripts/generate-combined-report.py
3. docs/validation-checks.md
4. README.md
5. CLAUDE.md

### Subagents That Could Help:
- gap-script-orchestrator: Can scaffold all files and updates

Approve this plan? Would you like me to invoke gap-script-orchestrator?
```

**After User Says "Yes" or "Proceed":**
```
[Invoke Agent tool with gap-script-orchestrator]
[Wait for completion]
[Provide summary]
```

### Pattern 2: Low-Impact Change - Proceed Directly

**User:** "Fix the typo in gap-aws-sts.py line 42"

**Your Response:**
```
Fixed typo in scripts/gap-aws-sts.py:42
- "occured" → "occurred"

Done!
```

**No plan, no subagents needed.**

### Pattern 3: Validation Logic Change - Assess Impact

**User:** "I modified gap-aws-sts.py to add CHECK #2"

**Your Response:**
```
## Implementation Plan

Adding CHECK #2 is a high-impact change.

### Impact Analysis:
- Output format changes (now shows 2 checks)
- Templates need updating
- Skills need updating
- Documentation needs CHECK #2 details

### Files Affected:
1. scripts/gap-aws-sts.py (validation logic)
2. scripts/templates/aws-sts.{md,html}.j2 (display 2 checks)
3. skills/aws-sts-gap/SKILL.md (document CHECK #2)
4. docs/validation-checks.md (add CHECK #2 section)

### Subagents:
- skills-reviewer: Can update skill file
- docs-reviewer: Can update documentation

Approve this approach? Should I invoke the subagents?
```

### Pattern 4: Shared Library Change - Check Templates

**User:** "I modified scripts/lib/ack_validation.py to add a 'warnings' field to the result"

**Your Response:**
```
## Implementation Plan

This is a high-impact change affecting template rendering.

### Impact Analysis:
- Added `warnings` field to validation result structure
- All templates that display validation results need updating
- Templates must render warnings separately from errors

### Files Affected:
1. scripts/lib/ack_validation.py (validation logic - already done)
2. scripts/gap-aws-sts.py (may need to pass warnings to templates)
3. scripts/gap-gcp-wif.py (same as above)
4. scripts/templates/aws-sts.html.j2 (add warnings display section)
5. scripts/templates/gcp-wif.html.j2 (add warnings display section)
6. scripts/templates/full-gap.html.j2 (add warnings display section)

### Subagents:
- gap-script-orchestrator: Can update all affected templates and scripts

Approve this plan? Should I invoke gap-script-orchestrator?
```

**After User Says "Yes" or "Proceed":**
```
[Invoke Agent tool with gap-script-orchestrator]
[Wait for completion]
[Provide summary of template updates]
```

## When NOT to Suggest Subagents

**Don't suggest subagents if:**
- Low-impact change (see when-to-plan.md)
- User is asking a question about how something works (informational)
- User is reading/exploring code (not making changes)
- Changes are only to tests or non-gap files
- User explicitly says "don't orchestrate" or "just show me"
- Simple bug fix without output changes

## Phrasing Guidelines

**Good (Show Plan, Suggest, Ask):**
- "Here's the implementation plan... Approve?"
- "The gap-script-orchestrator could handle this. Invoke it?"
- "I suggest using docs-reviewer to sync documentation. Proceed?"

**Bad (Auto-execute without permission):**
- "I'm spawning gap-script-orchestrator now..." ❌
- "Orchestrating the changes..." [without asking] ❌
- [Spawning agents without approval] ❌

## Quality Assurance Responsibility

Remember: In this repository, **you are responsible for identifying what needs updating**. The subagents help you ensure:

1. **No missing templates** when scripts are added
2. **No outdated templates** when validation result structures change (e.g., adding `warnings` field, new comparison categories)
3. **No outdated documentation** when behavior changes
4. **No orphaned files** when scripts are removed
5. **No inconsistent check numbering** across files
6. **Template-data synchronization** when shared libraries (`scripts/lib/*.py`) modify return structures

**Your job:** Identify high-impact changes, show plan, suggest appropriate subagents, wait for approval.

**Critical Reminder:** When modifying:
- `scripts/lib/ack_validation.py` → Check **ALL** templates that use `validation_details`
- `scripts/gap-*.py` comparison logic → Check templates that use `comparison`
- Any function returning data to templates → Check template compatibility

## Exception: User Override

If user says:
- "Don't orchestrate, I'll do it manually"
- "Skip the automation for now"
- "Just tell me what needs updating"

Then respect their preference and provide guidance instead of spawning agents.

## Integration with Hooks

When hooks output messages like:
```
⚠️  README.md not updated (may need validation table update)
```

You should:
1. Acknowledge the hook's finding
2. Suggest appropriate subagent to fix it
3. **Ask for approval** before spawning
4. After approval, spawn and report what was done

**Example:**
```
The pre-commit hook detected documentation is out of sync.

I can spawn docs-reviewer to fix this. Would you like me to proceed?
```

**After user says "yes":**
```
[Spawn docs-reviewer]
[Apply updates]
[Confirm sync]

✅ Documentation updated. Hook validation should pass now.
```

## Success Criteria

You're following these rules correctly when:
✅ High-impact changes show plan before proceeding
✅ Low-impact changes proceed without planning overhead
✅ Subagents suggested when relevant
✅ User approval obtained before spawning agents
✅ User can focus on script logic, not orchestration

You're NOT following these rules if:
❌ Auto-spawning agents without permission
❌ Showing plans for trivial changes
❌ Skipping plans for high-impact changes
❌ Not suggesting helpful subagents
❌ Ignoring impact classification (see when-to-plan.md)
