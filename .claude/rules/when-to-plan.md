# When to Show Implementation Plans

Decision matrix for determining when Claude should show a high-level plan before making changes.

## Core Principle

**High-Impact Changes** require planning and approval.
**Low-Impact Changes** can proceed directly without planning overhead.

## Rule Precedence

This rule takes precedence when determining workflow:
1. **This file (when-to-plan.md)** defines high vs low impact classification
2. **proactive-agent-usage.md** defines how to suggest and invoke subagents
3. Domain-specific rules (gap-script-orchestration.md, proactive-cleanup-suggestions.md) define WHAT needs updating, but MUST align with the "show plan → suggest → ask approval" workflow

**If uncertain:** Default to show plan → suggest agents → wait for approval.

## Impact Classification

### 🔴 High-Impact Changes (MUST Show Plan)

Changes that affect **multiple areas** or **external interfaces**:

| Change Type | Why High-Impact | Affected Areas |
|-------------|-----------------|----------------|
| **New gap script** | Creates dependencies across entire codebase | Script, templates, gap-all.sh, generate-combined-report.py, skills, docs, CLAUDE.md, README.md |
| **Remove gap script** | Breaks dependencies across codebase | Same as above |
| **Change validation logic** | Affects check behavior, outputs, documentation | Script, docs, skills, possibly CLAUDE.md |
| **Change script output format** | Affects reports, templates, skills | Script, templates, docs, skills |
| **Change report structure** | Affects templates, aggregation, consumers | Templates, generate-combined-report.py, docs |
| **Add/remove CLI flags** | Affects documentation, skills, users | Script, docs, skills |
| **Change exit code behavior** | Affects CI/CD, documentation | Script, docs, CLAUDE.md |
| **Modify shared libraries** | Affects all scripts that import them | Lib file, all dependent scripts, possibly docs |
| **Architecture changes** | Affects patterns, CLAUDE.md | Multiple files, CLAUDE.md |
| **Add new validation check** | Affects check numbering globally | Script, docs, README, CLAUDE.md, skills |

**Process for High-Impact:**
1. ✅ Analyze what needs updating
2. ✅ Show high-level implementation plan
3. ✅ List affected files
4. ✅ Suggest relevant subagents
5. ✅ Wait for approval ("proceed", "yes", "approved")
6. ✅ Execute after approval

**Example Plan Format:**
```markdown
## Implementation Plan

### Changes Required:
1. Create scripts/gap-network.py
2. Create templates (network.md.j2, network.html.j2)
3. Update gap-all.sh (add before feature gates)
4. Update generate-combined-report.py
5. Create skills/network-gap/SKILL.md
6. Update docs/validation-checks.md
7. Update README.md (check count table)
8. Update CLAUDE.md (validation table)

### Subagents That Could Help:
- gap-script-orchestrator: Scaffolds all files
- docs-reviewer: Ensures docs sync

Approve this plan?
```

### 🟢 Low-Impact Changes (Proceed Directly)

Changes that are **internal** and don't affect **external interfaces**:

| Change Type | Why Low-Impact | Proceed Without Plan |
|-------------|----------------|---------------------|
| **Bug fixes** | Same behavior, just fixes errors | ✅ Yes |
| **Refactoring** | Same inputs/outputs, cleaner code | ✅ Yes |
| **Add comments/docstrings** | Documentation only, no behavior change | ✅ Yes |
| **Fix typos** | No functional impact | ✅ Yes |
| **Internal optimizations** | Same behavior, better performance | ✅ Yes |
| **Add logging** | Doesn't change script behavior or output | ✅ Yes |
| **Variable renaming** | Internal only, no API change | ✅ Yes |
| **Code formatting** | Style only | ✅ Yes |

**Process for Low-Impact:**
1. ✅ Make the change directly
2. ✅ Explain what was changed (brief)
3. ❌ No plan needed
4. ❌ No approval gate

**Example Response:**
```markdown
I've fixed the typo in line 42 of gap-aws-sts.py:
- "occured" → "occurred"

Done!
```

## Edge Cases & Guidelines

### 🟡 Medium-Impact (Use Judgment)

Some changes are borderline. Use these guidelines:

| Scenario | High or Low? | Reasoning |
|----------|--------------|-----------|
| Add validation to existing check | 🟡 → 🟢 Low | If output format unchanged, docs don't need update |
| Add validation AND new output field | 🟡 → 🔴 High | Output format changed, templates affected |
| Refactor shared library function | 🟡 → 🟢 Low | If signature unchanged (same inputs/outputs) |
| Refactor AND change function signature | 🟡 → 🔴 High | All callers affected, need review |
| Add optional CLI flag | 🟡 → 🟢 Low | Doesn't break existing usage |
| Change required CLI flag | 🟡 → 🔴 High | Breaks existing usage, docs needed |
| Fix bug that changes output | 🟡 → 🔴 High | Output change affects reports, templates |
| Fix bug without output change | 🟡 → 🟢 Low | Internal fix only |

**When in doubt:** Ask yourself:
1. Does this affect files outside the one I'm editing? → High-Impact
2. Does this change what users see/experience? → High-Impact
3. Does this require documentation updates? → High-Impact
4. Otherwise → Low-Impact

## Subagent Usage Rules

### High-Impact Changes
- **SUGGEST** subagents that could help
- **WAIT** for user to approve/invoke
- **DON'T** auto-spawn without permission

**Phrasing:**
```
The gap-script-orchestrator subagent could handle steps 1-5.
Would you like me to invoke it, or handle this manually?
```

### Low-Impact Changes
- **OPTIONAL** to mention subagents
- Usually not needed for small changes
- Can proceed directly

## Examples

### Example 1: New Gap Script (High-Impact)

**User:** "Add a new gap script for network configuration"

**Claude Response:**
```
## Implementation Plan

This is a high-impact change affecting multiple areas.

### Files to Create:
1. scripts/gap-network.py (validation logic)
2. scripts/templates/network.md.j2
3. scripts/templates/network.html.j2
4. skills/network-gap/SKILL.md

### Files to Update:
1. scripts/gap-all.sh (add execution step)
2. scripts/generate-combined-report.py (add to aggregation)
3. docs/validation-checks.md (add check #7)
4. README.md (update check count)
5. CLAUDE.md (update validation table)

### Subagents:
- gap-script-orchestrator can scaffold everything
- docs-reviewer can update documentation

Approve this plan?
```

### Example 2: Fix Typo (Low-Impact)

**User:** "There's a typo in gap-aws-sts.py line 42"

**Claude Response:**
```
Fixed the typo in scripts/gap-aws-sts.py:42
- "occured" → "occurred"

Done!
```

### Example 3: Add Validation Logic (Edge Case → Low)

**User:** "Add URL validation to the fetch function in ack_validation.py"

**Claude Response:**
```
Adding URL validation to fetch_yaml_from_url() in scripts/lib/ack_validation.py.

This is internal validation - no output format changes, so proceeding directly.

[Makes change]

Added:
- URL format validation
- Better error message on invalid URLs

Function signature unchanged, all callers work as before.
```

### Example 4: Change Output Format (Edge Case → High)

**User:** "Add a 'severity' field to validation errors"

**Claude Response:**
```
## Implementation Plan

This is a high-impact change - adding a new output field.

### Impact Analysis:
- Output structure changes: validation error dict gets 'severity' key
- Templates need to display severity
- Skills need to mention severity in output examples
- Docs may need to explain severity levels

### Files Affected:
1. scripts/lib/ack_validation.py (add severity to errors)
2. scripts/templates/*.j2 (display severity in reports)
3. skills/*-gap/SKILL.md (update output examples)
4. docs/reports.md (document severity field)

### Approach:
1. Add severity to error dict structure
2. Update all templates to show severity
3. Update documentation

Proceed with this plan?
```

## Anti-Patterns

❌ **Don't** show plan for trivial changes:
```
User: "Fix the typo 'teh' → 'the'"
Claude: "Here's my implementation plan: [2 paragraphs]" ❌
```

❌ **Don't** skip plan for impactful changes:
```
User: "Add a new gap script"
Claude: [Creates 8 files without showing plan] ❌
```

❌ **Don't** auto-spawn subagents without approval:
```
User: "I added gap-network.py"
Claude: [Spawns gap-script-orchestrator immediately] ❌
```

## Decision Tree

```
User mentions gap script change or file modification
  ↓
Is it high-impact? (check classification table above)
  ├─ YES (High-Impact)
  │    ↓
  │  Show implementation plan
  │    ↓
  │  List all affected files
  │    ↓
  │  Suggest relevant subagents
  │    ↓
  │  Wait for user approval
  │    ↓
  │  User says "yes" / "proceed" / "approved"
  │    ↓
  │  Spawn subagents (gap-script-orchestrator, docs-reviewer, etc.)
  │    ↓
  │  Report results
  │
  └─ NO (Low-Impact)
       ↓
     Make change directly
       ↓
     Brief explanation (1-2 sentences)
       ↓
     Done (no plan, no approval needed)
```

## Success Criteria

You're following these rules correctly when:
✅ Plans shown for new scripts, validation changes, output changes
✅ No plans for typos, comments, internal refactoring
✅ Subagents suggested but not auto-invoked
✅ User approves before high-impact changes executed
✅ Low-impact changes happen quickly without overhead

You're NOT following these rules if:
❌ Showing plans for every tiny change
❌ Making high-impact changes without approval
❌ Auto-spawning subagents
❌ Unclear about what requires planning
