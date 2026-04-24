# Gap Script Orchestration Rules

When a gap analysis script is added, updated, or removed, multiple related files MUST be kept in sync.

## Prerequisites

Read these rules first:
- `.claude/rules/when-to-plan.md` - Determines if change is high-impact
- `.claude/rules/proactive-agent-usage.md` - Defines approval workflow

**This rule defines WHAT needs updating when gap scripts change.**
**Those rules define HOW to get user approval before making changes.**

## Orchestration Instructions

**IMPORTANT**: When you (Claude) detect that gap scripts have been modified (via user message, hook output, or file diff), you MUST:
1. Identify this as a **high-impact change** (per when-to-plan.md)
2. Show an implementation plan listing all affected files
3. Suggest the appropriate subagents (gap-script-orchestrator, docs-reviewer, etc.)
4. **Wait for user approval** before spawning any subagents

### Detection Triggers

If you observe ANY of these conditions:
- User mentions adding/updating/removing a gap script
- Hook output shows gap script changes
- User asks about orchestrating changes
- File diff shows `scripts/gap-*.py` changes

### Required Actions

You MUST:

1. **Show implementation plan** with all affected files (see Change Dependencies Matrix below)

2. **Suggest gap-script-orchestrator subagent:**
   ```
   The gap-script-orchestrator subagent can handle orchestrating all related
   changes: templates, gap-all.sh, generate-combined-report.py, skills, and
   documentation.
   
   Would you like me to invoke it?
   ```

3. **After user approves, spawn gap-script-orchestrator:**
   - Wait for orchestrator to complete
   - Optionally spawn reviewers in parallel (docs-reviewer, skills-reviewer, claude-md-updater)
   - Provide summary of all changes made

### Correct Workflow Example

When user says: "I just added scripts/gap-network.py"

✅ **CORRECT Response:**
```
## Implementation Plan

This is a high-impact change affecting multiple areas.

### Files to Create:
1. scripts/gap-network.py (validation logic)
2. scripts/templates/network.html.j2
3. skills/network-gap/SKILL.md

### Files to Update:
1. scripts/gap-all.sh (add execution step before feature gates)
2. scripts/generate-combined-report.py (add to aggregation)
3. docs/validation-checks.md (add check #7)
4. README.md (update validation checks table)
5. CLAUDE.md (update validation table)

### Subagents That Could Help:
- gap-script-orchestrator: Can scaffold all files and updates
- docs-reviewer: Can update documentation
- skills-reviewer: Can update skills

Approve this plan? Would you like me to invoke gap-script-orchestrator?
```

**After user says "yes" or "proceed":**
```
[Spawns gap-script-orchestrator agent]
[Waits for completion]
[Spawns docs-reviewer, skills-reviewer, claude-md-updater in parallel if needed]
[Provides comprehensive summary]
```

❌ **INCORRECT Response (violates when-to-plan.md):**
```
I've detected a new gap script. Let me orchestrate all the related changes.

[Immediately spawns gap-script-orchestrator without asking]
```

## Change Dependencies Matrix

| Change Type | Affected Files | Action Required |
|-------------|---------------|-----------------|
| **New gap script** | `scripts/gap-{name}.py` | Create with standard imports, validation logic, report generation |
| | `scripts/templates/{name}.html.j2` | Create HTML template |
| | `scripts/gap-all.sh` | Add execution step (before feature gates) |
| | `scripts/generate-combined-report.py` | Add to report aggregation |
| | `skills/{name}-gap/SKILL.md` | Create Claude skill |
| | `docs/validation-checks.md` | Document new check number |
| | `CLAUDE.md` | Update validation checks table, shared libraries |
| | `README.md` | Update validation checks table |
| **Update gap script** | Same script file | Modify logic |
| | Related template | Update if output structure changes |
| | `docs/validation-checks.md` | Update if check behavior changes |
| | Skill file | Update if workflow changes |
| | `CLAUDE.md` | Update if architectural patterns change |
| **Update shared library** | `scripts/lib/ack_validation.py` | Modify validation logic |
| | **ALL templates** | **ALWAYS check if templates need updating when result structure changes** (e.g., adding `warnings` field, new comparison categories) |
| | `scripts/templates/aws-sts.html.j2` | Update if validation_details structure changes |
| | `scripts/templates/gcp-wif.html.j2` | Update if validation_details structure changes |
| | `scripts/templates/full-gap.html.j2` | Update if validation_details structure changes |
| | `scripts/gap-*.py` files | Update if function signatures change |
| | `scripts/lib/reporters.py` | Update if report data structures change |
| | **ALL templates** | **ALWAYS check if new fields need display** (e.g., continues_default_hypershift for feature gates) |
| | `scripts/templates/feature-gates.html.j2` | Update if comparison structure changes |
| | `scripts/templates/full-gap.html.j2` | Update if comparison structure changes |
| **Remove gap script** | Delete script file | Remove file |
| | Delete template | Remove HTML template |
| | `scripts/gap-all.sh` | Remove execution step |
| | `scripts/generate-combined-report.py` | Remove from aggregation |
| | Delete skill | Remove skill directory |
| | `docs/validation-checks.md` | Remove or mark deprecated |
| | `CLAUDE.md` | Update validation table |
| | `README.md` | Update validation table |

## Critical Ordering Rules

1. **Feature Gates ALWAYS runs last** in `gap-all.sh` - even when new scripts added
2. **Check numbers are globally sequential** - new checks get next available number
3. **Informational checks** (like feature gates) should NOT cause exit 1
4. **Validation checks** (resources/acks) SHOULD cause exit 1 on FAIL

## Standard Gap Script Template Structure

```python
#!/usr/bin/env python3
"""<Description> Gap Analysis - Compare <what> between OpenShift versions."""

import argparse
import sys
from pathlib import Path

# Standard import pattern
sys.path.insert(0, str(Path(__file__).parent / 'lib'))
from common import log_info, log_success, log_error, log_warning, check_command
from openshift_releases import resolve_baseline_version, resolve_target_version
from reporters import generate_html_report, generate_json_report

def main():
    parser = argparse.ArgumentParser(description='<Description>')
    parser.add_argument('--baseline', help='Baseline version')
    parser.add_argument('--target', help='Target version')
    parser.add_argument('--report-dir', default='reports', help='Report directory')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')
    args = parser.parse_args()
    
    # Version resolution
    baseline = args.baseline or resolve_baseline_version()
    target = args.target or resolve_target_version()
    
    # Check dependencies
    check_command('oc')  # or other required tools
    
    # Perform analysis
    # ...
    
    # Generate reports
    template_data = {
        'type': '<Analysis Type>',
        'baseline': baseline,
        'target': target,
        'comparison': comparison_result,
        'validation': validation_result
    }
    
    generate_html_report('<type>', template_data, args.report_dir)
    generate_json_report('<type>', template_data, args.report_dir)
    
    # Exit code logic
    if validation_failed:
        sys.exit(1)
    sys.exit(0)

if __name__ == '__main__':
    main()
```

## Template Requirements

**HTML Template (`scripts/templates/{name}.html.j2`):**
- Bootstrap/custom CSS styling
- Color-coded changes (green=added, red=removed, orange=changed)
- Responsive tables
- Include check number in header
- Display validation results with ✓/✗ symbols
- Show added/removed items
- Include GitHub URLs for managed-cluster-config files
- Timestamp and version info

## gap-all.sh Integration Pattern

Add script execution in this order:
1. AWS STS (checks 1-2)
2. GCP WIF (checks 3-4)
3. OCP Gate Ack (check 5)
4. **[NEW SCRIPT HERE]** (check N)
5. Feature Gates (check 6) - ALWAYS LAST

```bash
# Run <New> analysis
log_info ""
log_info "Running <New> Gap Analysis..."
if python3 "${SCRIPT_DIR}/gap-<new>.py" \
    --baseline "$BASELINE" \
    --target "$TARGET" \
    --report-dir "$REPORT_DIR" \
    $VERBOSE_FLAG 2>&1; then
    new_result=0
else
    new_result=1
fi
```

Update exit logic:
```bash
if [[ $aws_result -eq 1 ]] || [[ $gcp_result -eq 1 ]] || ... || [[ $new_result -eq 1 ]]; then
    exit 1
fi
```

## Skill File Structure

Location: `skills/{name}-gap/SKILL.md`

Required frontmatter:
```yaml
---
name: {name}-gap
description: >
  Brief description of what this analyzes
compatibility:
  required_tools:
    - oc
    - python3
    - PyYAML
---
```

Required sections:
- When to Use
- What This Analyzes
- Workflow (3-4 steps)
- Example Interaction
- Output format

## Pre-commit Validation Checklist

Before committing changes involving gap scripts:

- [ ] Script follows standard import pattern
- [ ] HTML template exists
- [ ] gap-all.sh updated (if new/removed script)
- [ ] generate-combined-report.py updated (if new/removed script)
- [ ] Check number assigned and documented
- [ ] Skill file created/updated
- [ ] docs/validation-checks.md updated
- [ ] CLAUDE.md validation table updated
- [ ] README.md validation table updated
- [ ] Feature gates still runs LAST in gap-all.sh

## Documentation Update Requirements

**docs/validation-checks.md:**
- Add row to check numbering table
- Add "Check Execution by Script" entry
- Add detailed validation section with examples

**CLAUDE.md:**
- Update validation checks table
- Update shared library structure if new lib files added
- Update essential commands if new patterns introduced

**README.md:**
- Update validation checks table (6 checks → N checks)
- Update examples if relevant

## Anti-Patterns to Avoid

❌ **Don't** add scripts without templates - reports will fail to generate
❌ **Don't** skip check number assignment - creates confusion
❌ **Don't** add scripts after feature gates in gap-all.sh - violates ordering rule
❌ **Don't** forget to update generate-combined-report.py - combined report will be incomplete
❌ **Don't** use different template variable names - breaks consistency
❌ **Don't** exit 1 for informational checks - creates false CI failures

## Quick Reference Commands

```bash
# Verify all dependencies for a script are in place
./ci/prow/trigger-job.sh -j <job-name>  # Test in CI

# Check template syntax
python3 -c "from jinja2 import Template; Template(open('scripts/templates/new.html.j2').read())"

# Validate script runs
python3 scripts/gap-new.py --baseline 4.21 --target 4.22

# Check reports generated
ls -lh reports/gap-analysis-new_*
```
