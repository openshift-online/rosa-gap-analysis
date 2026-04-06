# Command Execution & Permissions Rules

Instructions for when Claude should ask for permission vs proceed directly with commands and file operations.

## Core Principle

**Read-only operations**: Proceed directly without asking
**Modification operations**: Always ask for approval first

## Prerequisites

These rules work together with:
- `.claude/rules/when-to-plan.md` - Impact classification
- `.claude/rules/proactive-agent-usage.md` - Subagent approval workflow
- `.claude/rules/gap-script-orchestration.md` - File update orchestration

---

## Command Execution Rules

### ✅ PROCEED DIRECTLY (No Approval Needed)

**Read-only commands** - Safe to run without asking:

```bash
# File reading
cat, head, tail, less, more, grep, awk, sed (read mode)

# Directory operations
ls, find, tree, pwd, cd

# Search operations
grep, rg, ag, ack

# File inspection
wc, file, stat, du, diff

# Text processing
sort, uniq, cut, paste, tr, column

# Archive inspection
tar -tzf, unzip -l, gzip -l

# Git read operations
git status, git log, git diff, git show, git branch -l, git ls-files

# Process inspection
ps, top, htop (inspection only)

# System info
uname, hostname, whoami, id, env, printenv

# Python/Bash inspection
python3 -c "..." (read/parse only), bash -n (syntax check)
```

**Temporary directory operations** - Safe if not affecting repo:
```bash
# Operations in /tmp, mktemp directories, or other temp locations
mkdir /tmp/test-dir
cd /tmp && ./script.sh
python3 script.py --output /tmp/output.json
```

**Validation commands** - Based on `.claude/` configuration:
```bash
# Pre-commit hook execution
./.claude/hooks/pre-commit

# Validation scripts (if they don't modify files)
./scripts/validate-something.sh

# Linting (read-only checks)
python3 -m pylint --errors-only scripts/
shellcheck scripts/*.sh
```

**Test execution** - Cleanup-analyzer can run automatically:
```bash
# cleanup-analyzer running tests
./scripts/gap-all.sh --baseline 4.21 --target 4.22  # During cleanup validation
python3 ./scripts/gap-*.py --baseline X --target Y   # Individual script tests
```

---

### ⚠️ ASK FOR APPROVAL FIRST

**File modification commands:**
```bash
# File operations
rm, mv, cp (modifying existing files), touch (new files)

# Editors
vi, vim, nano, emacs (opening files for edit)

# File creation/deletion
> file.txt, >> file.txt, cat > file.txt

# Archive operations
tar -xzf, unzip, gunzip (extracting files)
```

**EXCEPTION:** Files updated per rules/subagents workflow:
- Show summary of changes (diff or description)
- Wait for user approval
- Apply after "yes"/"proceed"

**Git operations** (ALL require approval):
```bash
# Commits
git add, git commit, git commit --amend

# Branch operations
git checkout, git switch, git branch -d, git branch -D

# Remote operations
git push, git pull, git fetch, git clone

# History modification
git reset, git rebase, git cherry-pick, git revert

# Stash operations
git stash, git stash pop

# Tag operations
git tag (creating/deleting)

# Merge operations
git merge
```

**Phrasing for git operations:**
```
I need to run: git commit -m "Fix validation"

This will create a new commit with the staged changes. Proceed? [y/n]
```

**Adding new files:**
```bash
# Creating new scripts, configs, docs
touch new-file.py
cat > new-script.sh
mkdir new-directory && ...
```

**Phrasing for new files:**
```
I need to create a new file: scripts/lib/credential_extraction.py

This will add a shared library for credential extraction logic.
Proceed? [y/n]
```

**Removing files:**
```bash
# Deletion operations
rm file.txt, rm -rf directory/, git rm file.txt
```

**Phrasing for file deletion:**
```
I need to delete: .claude/hooks/post-file-change

This file is unused and no longer referenced. Proceed? [y/n]
```

**Installing dependencies:**
```bash
# Package managers
pip install, pip3 install, npm install, yarn add
apt-get install, yum install, brew install
```

**Phrasing for dependencies:**
```
I need to install a new dependency: pip install jinja2

This is required for the new template rendering feature.
Proceed? [y/n]
```

---

## File Update Workflow

When updating existing files per rules/subagents:

### Step 1: Show Summary of Changes

**For single file updates:**
```
I need to update CLAUDE.md line 175:

BEFORE:
- `common.sh`, `openshift-releases.sh` - Bash equivalents

AFTER:
- `logging.sh` - Bash logging functions
- `openshift-releases.sh` - Bash version resolution

Proceed with this change? [y/n]
```

**For multi-file updates:**
```
## Summary of Changes

Files to update:
1. skills/aws-sts-gap/SKILL.md - Add jq to required_tools
2. skills/gcp-wif-gap/SKILL.md - Add jq to required_tools

Both changes add:
  + - jq (for JSON processing)

Proceed with these 2 updates? [y/n]
```

### Step 2: Wait for Approval

- User says "y", "yes", "proceed", "approved" → Apply changes
- User says "n", "no", "skip" → Don't apply changes
- User says "show me" → Show full diff before applying

### Step 3: Apply and Confirm

```
✅ Updated 2 files:
- skills/aws-sts-gap/SKILL.md
- skills/gcp-wif-gap/SKILL.md
```

---

## Special Cases

### Case 1: Cleanup-analyzer Testing

**Automatic testing allowed:**
```bash
# cleanup-analyzer runs these automatically
./scripts/gap-all.sh --baseline 4.21 --target 4.22
python3 ./scripts/gap-aws-sts.py --baseline 4.21 --target 4.22
python3 ./scripts/gap-gcp-wif.py --baseline 4.21 --target 4.22
# etc.
```

**Why:** Testing is non-destructive and required for validation. Reports go to /tmp or reports/ directory (gitignored).

**Rollback:** If tests fail, cleanup-analyzer automatically rolls back changes.

### Case 2: Subagent File Updates

**When gap-script-orchestrator, docs-reviewer, etc. update files:**

1. ✅ Show summary of what will be updated
2. ✅ Ask for approval
3. ✅ Apply after "yes"
4. ❌ Don't ask for individual file operations (already approved in bulk)

**Example:**
```
gap-script-orchestrator will update 8 files:
- Create: scripts/gap-network.py, templates/network.{md,html}.j2
- Update: gap-all.sh, generate-combined-report.py, README.md, CLAUDE.md
- Create: skills/network-gap/SKILL.md

Approve these changes? [y/n]
```

After approval, all 8 operations proceed without individual prompts.

### Case 3: Pre-commit Hook Execution

**Read-only validation:**
```bash
# Can run directly (syntax checks, grep searches)
./.claude/hooks/pre-commit
```

**If hook suggests fixes:**
```
⚠️ Pre-commit hook detected:
- scripts/gap-network.py missing templates

I can spawn docs-reviewer to fix this. Proceed? [y/n]
```

### Case 4: Temporary Test Environments

**Operations in temp directories are safe:**
```bash
# All these can proceed without asking
cd /tmp && git clone repo.git test-repo
cd /tmp/test-repo && make test
mkdir /tmp/gap-test && ./scripts/gap-all.sh --report-dir /tmp/gap-test

# Cleanup
rm -rf /tmp/test-repo  # Safe (not in repo)
```

**Rule:** If operation is entirely within `/tmp`, `mktemp`, or other temp locations → Proceed directly

---

## Integration with Other Rules

### With when-to-plan.md

| Change Type | when-to-plan.md | command-execution-permissions.md |
|-------------|-----------------|----------------------------------|
| New file | High-impact → Show plan | Ask approval before creating |
| Update file | Show plan if high-impact | Show summary, ask approval |
| Delete file | High-impact → Show plan | Ask approval before deleting |
| Read file | N/A | Proceed directly |

### With proactive-agent-usage.md

| Action | proactive-agent-usage.md | command-execution-permissions.md |
|--------|--------------------------|----------------------------------|
| Spawn subagent | Ask approval first | N/A |
| Subagent updates files | Show summary in plan | Ask approval before updates |
| Subagent runs tests | Part of workflow | Automatic (cleanup-analyzer) |

### With gap-script-orchestration.md

| Action | gap-script-orchestration.md | command-execution-permissions.md |
|--------|------------------------------|----------------------------------|
| Detect gap script change | Show plan, suggest orchestrator | N/A |
| Create templates | List in plan | Ask approval for new files |
| Update gap-all.sh | List in plan | Ask approval for modifications |

---

## Decision Tree

```
Command or operation needed
  ↓
Is it read-only? (grep, cat, ls, git status, etc.)
  ├─ YES → Proceed directly
  │
  └─ NO → Is it modifying files?
      ├─ YES → Is it updating existing files per rules/subagents?
      │   ├─ YES → Show summary → Ask approval → Apply
      │   └─ NO → Is it creating/deleting files?
      │       └─ YES → Ask approval first
      │
      └─ NO → Is it a git operation?
          ├─ YES → Ask approval first
          │
          └─ NO → Is it installing dependencies?
              ├─ YES → Ask approval first
              │
              └─ NO → Is it running in temp directory?
                  ├─ YES → Proceed directly
                  └─ NO → Ask approval to be safe
```

---

## Examples

### ✅ Example 1: Read-Only Commands (Proceed Directly)

**User:** "Check if gap-network.py exists"

**Claude:**
```
[Runs: ls scripts/gap-network.py]
File not found.
```

**No prompt needed** - ls is read-only.

---

### ✅ Example 2: File Update per Rules (Show Summary + Ask)

**User:** "Update CLAUDE.md to fix the shared libraries list"

**Claude:**
```
I need to update CLAUDE.md line 175:

BEFORE:
- `common.sh`, `openshift-releases.sh` - Bash equivalents

AFTER:
- `logging.sh` - Bash logging functions
- `openshift-releases.sh` - Bash version resolution

Proceed? [y/n]
```

**User:** "yes"

**Claude:** [Applies change] ✅ Updated CLAUDE.md

---

### ⚠️ Example 3: New File Creation (Ask First)

**User:** "Create a shared credential extraction library"

**Claude:**
```
I'll create a new file: scripts/lib/credential_extraction.py

This will contain the shared extract_credential_requests() function
used by both gap-aws-sts.py and gap-gcp-wif.py.

Proceed with creating this new file? [y/n]
```

**User:** "yes"

**Claude:** [Creates file] ✅ Created scripts/lib/credential_extraction.py

---

### ⚠️ Example 4: Git Operation (Ask First)

**User:** "Commit these changes"

**Claude:**
```
I need to run: git commit -m "Add jq to skill dependencies"

This will create a new commit with the 2 staged files:
- skills/aws-sts-gap/SKILL.md
- skills/gcp-wif-gap/SKILL.md

Proceed? [y/n]
```

**User:** "yes"

**Claude:** [Runs git commit] ✅ Committed changes

---

### ✅ Example 5: Cleanup-analyzer Testing (Automatic)

**Cleanup-analyzer:** "Running baseline tests..."

```
[Runs: ./scripts/gap-all.sh --baseline 4.21 --target 4.22]
✓ All scripts exit 0
✓ Reports generated

[Applies cleanup changes]

[Runs: ./scripts/gap-all.sh --baseline 4.21 --target 4.22]
✓ All scripts exit 0
✓ Reports generated
✓ JSON structure matches

✅ Cleanup complete, all tests passed.
```

**No prompts needed** - Testing is automatic per cleanup-analyzer workflow.

---

### ✅ Example 6: Temp Directory Operations (Proceed Directly)

**User:** "Test this in a temporary directory"

**Claude:**
```
[Runs: mkdir /tmp/gap-test]
[Runs: ./scripts/gap-all.sh --report-dir /tmp/gap-test]
[Runs: ls /tmp/gap-test]

Reports generated in /tmp/gap-test/:
- gap-analysis-full_4.21_to_4.22_*.md
- gap-analysis-full_4.21_to_4.22_*.html
```

**No prompts needed** - All operations in /tmp.

---

## Anti-Patterns

❌ **Don't ask for read-only commands:**
```
User: "Check the file size"
Claude: "Can I run 'wc -l file.txt'?" ❌
```

✅ **Correct:**
```
User: "Check the file size"
Claude: [Runs: wc -l file.txt]
185 file.txt
```

---

❌ **Don't proceed with git operations without asking:**
```
User: "The changes look good"
Claude: [Runs: git commit] ❌
```

✅ **Correct:**
```
User: "The changes look good"
Claude: "Create a commit with these changes? [y/n]"
```

---

❌ **Don't ask for each file when bulk approved:**
```
User: "yes, update all 8 files"
Claude: "Update file 1? [y/n]" ❌
Claude: "Update file 2? [y/n]" ❌
```

✅ **Correct:**
```
User: "yes, update all 8 files"
Claude: [Updates all 8 files]
✅ Updated 8 files.
```

---

## Success Criteria

You're following these rules correctly when:
✅ Read-only commands run without prompts
✅ File modifications show summary and ask for approval
✅ Git operations always ask for approval
✅ New files/deletions ask for approval
✅ Bulk-approved operations don't ask individually
✅ Temp directory operations proceed freely
✅ cleanup-analyzer runs tests automatically

You're NOT following these rules if:
❌ Asking "Can I run ls/cat/grep?"
❌ Running git commit without approval
❌ Creating new files without asking
❌ Deleting files without approval
❌ Installing dependencies without asking
❌ Asking for each file in bulk-approved update
