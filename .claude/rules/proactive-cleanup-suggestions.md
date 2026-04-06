# Proactive Cleanup Suggestions

When repository complexity or size grows beyond target thresholds, Claude should proactively suggest cleanup analysis.

## Prerequisites

Follow the approval workflow from:
- `.claude/rules/when-to-plan.md` - Impact classification
- `.claude/rules/proactive-agent-usage.md` - Always ask approval before spawning cleanup-analyzer

**This rule defines WHEN to suggest cleanup.**
**Those rules define HOW to ask for approval.**

## Trigger Conditions

**Suggest cleanup when EITHER condition is met:**

| Trigger | Threshold | Reasoning |
|---------|-----------|-----------|
| **CLAUDE.md size** | ≥300 lines | Target: 250 lines. When CLAUDE.md grows, it signals architectural complexity is increasing. Time to simplify/consolidate. |
| **Large change** | ≥500 lines added in single change | Large additions often introduce duplication, unused code, or bloat. Review while context is fresh. |

## When to Check

**Timing:** AFTER high-impact change completes successfully
- ✅ After implementation is done and working
- ✅ After tests pass
- ✅ Before committing
- ❌ NOT during implementation (wait until done)
- ❌ NOT for low-impact changes

## Detection Logic

```bash
# After high-impact change completes:
1. Count CLAUDE.md lines
2. Count net lines added in change (git diff --stat)
3. If CLAUDE.md ≥300 OR lines_added ≥500:
   → Suggest cleanup-analyzer
```

## Prompt Pattern

**When CLAUDE.md reaches 300+ lines:**
```
⚠️  CLAUDE.md is now {N} lines (target: 250).
Architectural complexity is growing.

Run cleanup-analyzer to find simplification opportunities? [y/n]
```

**When change adds 500+ lines:**
```
✅ Complete! Added {N} lines across {M} files.

Run cleanup-analyzer to check for bloat/duplication? [y/n]
```

## User Response Handling

| Response | Action |
|----------|--------|
| `y`, `yes`, `proceed` | Spawn cleanup-analyzer subagent |
| `n`, `no`, `skip` | Skip cleanup, continue normally |
| `later` | Add note but don't run now |
| `disable` | User doesn't want cleanup suggestions (respect this) |

## What cleanup-analyzer Does

1. **Analyzes repository** for cleanup opportunities
2. **Ranks findings** by impact (lines saved, complexity reduced)
3. **Presents options** to user with effort/impact estimates
4. **User selects** which cleanups to apply
5. **Runs baseline tests** (gap-all.sh + individual gap-*.py scripts)
6. **Applies selected** cleanups
7. **Runs post-cleanup tests** (same tests, verify no regressions)
8. **Validates reports** (JSON structure comparison)
9. **Rolls back if tests fail** (never commits broken code)
10. **Reports results** with test confirmation

## Cleanup Categories

### If triggered by CLAUDE.md size (≥300 lines):

**Primary focus: Simplify CLAUDE.md**
- Consolidate verbose sections
- Remove redundant examples (move to docs/)
- Condense validation checks table
- Move detailed implementation notes to code comments
- Check if architectural patterns can be simplified

**Secondary: Codebase cleanup**
- Unused functions/imports
- Code duplication
- Bloated files

### If triggered by large change (≥500 lines):

**Primary focus: New code optimization**
- Unused functions/imports in new code
- Duplication between new and existing code
- Files >500 lines (suggest splitting)
- Overly verbose comments

**Secondary: Related cleanup**
- Consolidate similar patterns
- Remove orphaned files
- Update outdated documentation

## Testing Guarantees

**cleanup-analyzer ALWAYS tests before and after applying changes:**

✅ **Baseline tests** (before cleanup):
- Run gap-all.sh --baseline 4.21 --target 4.22
- Run all individual gap-*.py scripts
- Verify exit 0, reports generated

✅ **Post-cleanup tests** (after cleanup):
- Re-run gap-all.sh with same versions
- Re-run all individual gap-*.py scripts
- Verify exit 0, reports generated
- Compare JSON report structure

✅ **Automatic rollback**:
- If any test fails, rollback ALL changes
- Report failure to user with root cause
- Never commit broken code

## Anti-Patterns to Avoid

❌ **Don't skip testing** - MANDATORY before and after cleanup
❌ **Don't commit without testing** - Rollback if tests fail
❌ **Don't suggest cleanup during implementation** - Wait until work complete
❌ **Don't suggest for small changes** - <500 lines and CLAUDE.md <300: skip
❌ **Don't auto-run cleanup** - Always get user approval first
❌ **Don't suggest every time** - If user says "disable", respect it
❌ **Don't remove code without understanding** - Analyze dependencies first

## Integration with Other Rules

**Coordinates with:**
- `when-to-plan.md`: Cleanup happens AFTER implementation
- `proactive-agent-usage.md`: cleanup-analyzer is a suggested subagent
- `gap-script-orchestration.md`: Cleanup can identify orchestration issues

**Triggered by:**
- `claude-md-updater`: Reports when CLAUDE.md ≥300 lines
- Main Claude: Detects when change adds ≥500 lines

## Example Workflow

```
User: "Add gap-network.py" [High-impact change]
Claude: [Shows plan, gets approval, implements] +520 lines

Claude: "✅ Complete! Added 520 lines across 8 files.
         
         Run cleanup-analyzer to check for bloat/duplication? [y/n]"

User: "y"

Claude: [Spawns cleanup-analyzer subagent]

cleanup-analyzer: "
🧹 Cleanup Opportunities (ranked by impact):

CATEGORY: Code Duplication
1. HIGH: Consolidate credential validation logic in gap-*.py scripts
   - Impact: -89 lines
   - Effort: Medium (30 min)
   - Create shared validate_credentials() function in lib/validators.py

CATEGORY: Unused Code
2. MEDIUM: Remove 3 unused helper functions in lib/ack_validation.py
   - Impact: -47 lines
   - Effort: Low (10 min)
   - Functions: parse_legacy_format(), validate_v1_schema(), migrate_config()

CATEGORY: File Organization
3. LOW: Split gap-network.py (620 lines) into smaller modules
   - Impact: Better maintainability
   - Effort: High (2 hours)
   - Suggest: gap-network.py + lib/network_validation.py

Total potential reduction: 136 lines (4.8% of codebase)

Apply which cleanups? [1,2,3 / all / none]"

User: "1,2"

Claude: [Applies cleanups #1 and #2]
Claude: "✅ Cleanup complete: -136 lines, +1 shared function"
```

## Success Criteria

You're following this rule correctly when:
✅ Cleanup suggested when CLAUDE.md ≥300 or change ≥500 lines
✅ User approves before running cleanup-analyzer
✅ Cleanup happens AFTER implementation, not during
✅ User can decline ("no", "skip", "disable")
✅ CLAUDE.md stays around 250 lines due to proactive pruning

You're NOT following this rule if:
❌ Suggesting cleanup during implementation
❌ Suggesting cleanup for small changes (<500 lines, CLAUDE.md <300)
❌ Auto-running cleanup without approval
❌ Ignoring user "disable" preference
❌ CLAUDE.md growing unbounded past 300+ lines
