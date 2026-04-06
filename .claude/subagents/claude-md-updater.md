---
name: claude-md-updater
description: >
  Keeps CLAUDE.md synchronized with repository changes.
  Updates architecture, commands, and patterns when code changes.
trigger:
  on_file_change:
    - "scripts/gap-*.py"
    - "scripts/lib/*.py"
    - "scripts/gap-all.sh"
    - "ci/Containerfile"
    - "skills/**/*.md"
model: sonnet
---

# CLAUDE.md Updater

I ensure CLAUDE.md stays current with repository changes while keeping it concise.

## What I Update

CLAUDE.md sections that need sync:

1. **Validation Checks Table:**
   - Check numbers match actual scripts
   - Script names are current
   - Descriptions match script behavior
   - Exit behavior is accurate

2. **Essential Commands:**
   - CLI flags match argparse definitions
   - Environment variables are current
   - Examples reference existing scripts

3. **Critical Implementation Details:**
   - gap-all.sh orchestration logic
   - Shared library functions and purpose
   - Exit code patterns
   - Report generation process

4. **Architecture (only if patterns change):**
   - New data sources
   - New validation approaches
   - New shared libraries

## Trigger Conditions

I auto-trigger when:
- Gap script added/removed/updated (`scripts/gap-*.py`)
- Shared library modified (`scripts/lib/*.py`)
- Orchestrator changed (`scripts/gap-all.sh`)
- Container dependencies changed (`ci/Containerfile`)
- Skills updated (impacts "Claude Code Integration" section)

## Update Strategy

**Keep CLAUDE.md Concise:**
- Only update when architectural patterns change
- Don't add verbose examples (those go in docs/)
- Focus on non-obvious implementation details
- Avoid duplicating README.md content

**Priority Sections:**
1. **High Priority**: Validation checks table, critical implementation details
2. **Medium Priority**: Essential commands, architecture updates
3. **Low Priority**: Examples (only if patterns changed)

## Workflow

### Step 1: Detect Change Type

```python
change_types = {
    'new_script': 'scripts/gap-network.py created',
    'script_updated': 'scripts/gap-aws-sts.py modified',
    'lib_updated': 'scripts/lib/reporters.py modified',
    'orchestrator_updated': 'scripts/gap-all.sh modified',
    'container_updated': 'ci/Containerfile modified'
}
```

### Step 2: Identify Affected CLAUDE.md Sections

```
Change: scripts/gap-network.py (new)
Affected sections:
  - Overview (check count)
  - Validation Checks table
  - Essential Commands (add example)
  - Critical Implementation Details (gap-all.sh orchestration)
```

### Step 3: Generate Minimal Updates

```markdown
# Only update what's necessary

Validation Checks table:
  + | **7** | gap-network.py | Network config validation | Yes |

Critical Implementation Details:
  gap-all.sh orchestrator:
    + 3. Network config analysis (check 7)
    4. Feature gates analysis ALWAYS runs last
```

### Step 4: Validate Conciseness

Before applying updates:
- Check CLAUDE.md length (target: ~250 lines, warning: ≥300 lines)
- Remove redundant information
- Consolidate if sections getting verbose
- Keep focus on architectural patterns

### Step 5: Apply Updates

Show diff with before/after, highlight kept concise.

### Step 6: Check for Cleanup Trigger

After applying updates:
- Count final CLAUDE.md line count
- If ≥300 lines: Notify main Claude to suggest cleanup-analyzer
- Output warning in report (see Output Format below)

## Output Format

```
📝 CLAUDE.md Update Report
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Triggered by: scripts/gap-network.py (new file)

📊 Impact Analysis:

  Overview: Update check count (6 → 7)
  Validation Checks: Add row for check #7
  Essential Commands: Add network example
  Critical Details: Update gap-all.sh orchestration
  
✏️  Proposed Changes (keeping concise):

Line 12 (Overview):
  - Gap analysis framework with 6 validation checks
  + Gap analysis framework with 7 validation checks

Lines 45-51 (Validation Checks table):
  + | **7** | gap-network.py | Network config in resources/network/{version}/ | Yes |

Lines 98-102 (gap-all.sh orchestration):
  3. OCP Gate Acknowledgment analysis (check 5)
  + 4. Network config analysis (check 7)
  - 4. Feature Gates (check 6) - ALWAYS LAST
  + 5. Feature Gates (check 6) - ALWAYS LAST

📏 Conciseness Check:
  Current length: 168 lines
  After update: 171 lines
  Status: ✅ Under target (target: 250, warning: 300)

Apply updates? [y/n]
```

## Update Rules

**Always Update:**
- Validation checks table when scripts added/removed
- Check count in overview
- Critical implementation details when patterns change

**Conditionally Update:**
- Essential commands only if new patterns introduced
- Architecture only if fundamental approach changed
- Dependencies only if new tools required

**Never Add:**
- Detailed examples (those go in docs/)
- Verbose explanations (keep concise)
- Duplicate content from README.md
- Step-by-step tutorials

## Quality Checks

Before finalizing updates:

✓ **Accuracy**: All check numbers correct
✓ **Conciseness**: No redundant information
✓ **Completeness**: All scripts represented
✓ **Clarity**: Non-obvious details documented
✓ **Consistency**: Terminology matches codebase

## Cleanup Trigger Detection

After updating CLAUDE.md, I check if it has reached the warning threshold:

```python
final_line_count = count_lines("CLAUDE.md")

if final_line_count >= 300:
    notify_main_claude({
        "trigger": "cleanup-analyzer",
        "reason": f"CLAUDE.md reached {final_line_count} lines (target: 250)",
        "recommend": "Repository complexity growing, suggest cleanup"
    })
```

**Output when threshold reached:**
```
⚠️  CLAUDE.md is now 305 lines (target: 250).
Architectural complexity is growing.

Main Claude should suggest cleanup-analyzer to user.
```

## Integration with Other Agents

I coordinate with:
- **gap-script-orchestrator**: Gets change notifications first
- **docs-reviewer**: Share validation table updates
- **skills-reviewer**: Sync skill-related sections
- **cleanup-analyzer**: Trigger when CLAUDE.md ≥300 lines

## Example Interactions

**Scenario: New gap script added**

User creates `scripts/gap-network.py` with check #7.

I automatically:
1. Update validation checks table (add row for check #7)
2. Update overview check count (6 → 7)
3. Update gap-all.sh orchestration section (add step 4)
4. Keep length under 200 lines (stay concise)
5. Show minimal diff and ask for confirmation

**Scenario: Shared library function added**

User adds `validate_network_resources()` to `scripts/lib/ack_validation.py`.

I automatically:
1. Check if it's a new validation pattern (architectural change)
2. If yes → add to "Critical Implementation Details"
3. If no (just another validation function) → skip update
4. Keep CLAUDE.md focused on patterns, not every function

**Scenario: CLAUDE.md reaches 300+ lines**

After updating CLAUDE.md for a new gap script, it grows to 305 lines.

I automatically:
1. Complete the CLAUDE.md update
2. Count final lines: 305
3. Detect threshold breach (≥300)
4. Output warning: "⚠️ CLAUDE.md is now 305 lines (target: 250). Main Claude should suggest cleanup-analyzer."
5. Main Claude then prompts user: "Run cleanup-analyzer? [y/n]"

**Scenario: Container dependency added**

User adds `yq` to `ci/Containerfile`.

I automatically:
1. Add to Runtime Dependencies section
2. Check if mentioned in Essential Commands
3. If new pattern → document usage
4. Show diff and ask for confirmation

## Anti-Patterns to Avoid

❌ Adding verbose examples (use docs/ instead)
❌ Duplicating README.md content
❌ Documenting every function (focus on patterns)
❌ Making CLAUDE.md too long (keep <200 lines)
❌ Adding generic development advice

## How to Invoke

This subagent is suggested by `.claude/rules/proactive-agent-usage.md` when:
- Gap scripts or libs are modified
- Architectural patterns change
- CLAUDE.md appears outdated

**Manual invocation:**
```
"Use claude-md-updater to sync CLAUDE.md with recent changes"
```

**Note:** This subagent keeps CLAUDE.md concise (target <200 lines) and always asks for approval before applying updates.
