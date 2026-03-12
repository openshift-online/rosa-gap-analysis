---
name: full-gap-analysis
description: >
  Comprehensive cloud credential policy gap analysis between OpenShift versions covering
  both AWS STS and GCP WIF policies automatically. Use when performing complete version
  upgrade assessment for managed OpenShift (OSD, ROSA).
  Exits with code 0 if no differences in any platform, code 1 if differences found in at least one.
compatibility:
  required_tools:
    - oc
    - jq
    - yq or python3
---

# Full Gap Analysis

Orchestrate comprehensive gap analysis for cloud credential policies across OpenShift versions.
Automatically analyzes both AWS STS and GCP WIF platforms.

## When to Use

- Planning major version upgrades (e.g., 4.21 → 4.22)
- Comparing platform variants (ROSA Classic vs HCP)
- Cross-cloud comparison (OSD AWS vs GCP)
- Complete upgrade impact assessment for IAM/WIF policies
- Quarterly upgrade planning
- CI/CD pipelines that need to detect policy changes

## What This Analyzes

Automatically analyzes both platforms:

1. **AWS STS IAM Policies**
   - IAM permission changes
   - Service account requirements
   - Security posture changes

2. **GCP WIF Configurations**
   - Workload Identity Federation changes
   - GCP IAM role/permission changes
   - Service account bindings

The script runs both analyses and reports if differences exist in either platform.

## Workflow

### Step 1: Parse Request

Understand the comparison being requested:
- Baseline version (e.g., `4.21`)
- Target version (e.g., `4.22`)
- Specific focus areas (if any)

The analysis automatically covers both AWS STS and GCP WIF platforms.

### Step 2: Use the Orchestrator Script

The `scripts/gap-all.sh` script runs credential policy analysis for both AWS and GCP:
```bash
./scripts/gap-all.sh --baseline 4.21 --target 4.22
```

The script:
- Runs AWS STS policy analysis
- Runs GCP WIF policy analysis
- Exits with code 0 if no differences found in either platform
- Exits with code 1 if differences detected in at least one platform

**Use in CI/CD:**
```bash
if ./scripts/gap-all.sh --baseline 4.21 --target 4.22; then
  echo "No policy changes in any platform - safe to proceed"
else
  echo "Policy changes detected - review required"
  exit 1
fi
```

### Step 3: Interpret Results

The script provides pass/fail indication via exit codes. For detailed analysis:

**Extract comparison data manually:**
```bash
# Source the functions
source scripts/lib/common.sh
source scripts/gap-aws-sts.sh  # or gap-gcp-wif.sh

# Extract policies
baseline_policy=$(mktemp)
target_policy=$(mktemp)
get_sts_policy "4.21" > "$baseline_policy"
get_sts_policy "4.22" > "$target_policy"

# Compare and analyze
compare_sts_policies "$baseline_policy" "$target_policy" | jq '.'
```

### Step 4: Perform Deep Analysis

Go beyond the scripts by:
- **Security assessment**: Evaluate new permissions for security implications
- **Impact assessment**: Prioritize IAM/WIF changes by criticality
- **Timeline analysis**: Identify upgrade blockers related to credentials
- **Customer communication**: Draft IAM policy update notices

## Output

The script outputs log messages for both platforms and exits with appropriate code:

**No differences in any platform:**
```
[INFO] OpenShift Gap Analysis Suite
[INFO] Baseline: 4.21
[INFO] Target: 4.22
[INFO] Platforms: AWS STS, GCP WIF

[INFO] Running AWS STS Policy Gap Analysis...
[SUCCESS] No AWS STS policy differences found

[INFO] Running GCP WIF Policy Gap Analysis...
[SUCCESS] No GCP WIF policy differences found

[INFO] Gap Analysis Complete!
[SUCCESS] No policy differences found in any platform
```
Exit code: `0`

**Differences found in one or both platforms:**
```
[INFO] OpenShift Gap Analysis Suite
[INFO] Baseline: 4.21
[INFO] Target: 4.22
[INFO] Platforms: AWS STS, GCP WIF

[INFO] Running AWS STS Policy Gap Analysis...
[WARNING] AWS STS policy differences detected

[INFO] Running GCP WIF Policy Gap Analysis...
[SUCCESS] No GCP WIF policy differences found

[INFO] Gap Analysis Complete!
[WARNING] AWS STS: Policy differences detected
[WARNING] Policy differences detected - review required
```
Exit code: `1`

## Comparison Scenarios

### Version Upgrade (All Platforms)
```
Baseline: 4.21
Target: 4.22
```
Analyzes both:
- AWS STS IAM policy changes
- GCP WIF policy changes

Exit code indicates if differences exist in either platform.

## Enhanced Analysis

Provide additional insights:

### Prioritization Matrix
| Change | Impact | Effort | Priority |
|--------|--------|--------|----------|
| New STS permission | High | Low | P0 |
| Removed WIF role | High | Medium | P0 |
| Changed permission scope | Medium | Low | P1 |

### Timeline Recommendations
- **Before upgrade**: Update IAM roles/policies in AWS/GCP
- **During upgrade**: Monitor for permission denied errors
- **After upgrade**: Validate all credential-dependent workloads

### Risk Assessment
- **High risk**: New required permissions, removed roles
- **Medium risk**: Changed permission scopes
- **Low risk**: Added optional permissions

## Going Beyond Scripts

While scripts provide credential policy data, add strategic value:
- Executive summaries for leadership
- Technical deep-dives for platform engineers
- Customer-facing IAM policy update guides
- Security risk mitigation strategies
- Rollback procedures for IAM changes

## Example Interaction

**User**: "Check if policies changed between 4.21 and 4.22"

**Response**:
```bash
./scripts/gap-all.sh --baseline 4.21 --target 4.22
```

**If no changes in any platform:**
```
[INFO] OpenShift Gap Analysis Suite
[INFO] Running AWS STS Policy Gap Analysis...
[SUCCESS] No AWS STS policy differences found
[INFO] Running GCP WIF Policy Gap Analysis...
[SUCCESS] No GCP WIF policy differences found
[SUCCESS] No policy differences found in any platform
```
Exit code: `0` - Safe to proceed

**If changes detected in at least one platform:**
```
[INFO] OpenShift Gap Analysis Suite
[INFO] Running AWS STS Policy Gap Analysis...
[WARNING] AWS STS policy differences detected
[INFO] Running GCP WIF Policy Gap Analysis...
[SUCCESS] No GCP WIF policy differences found
[WARNING] AWS STS: Policy differences detected
[WARNING] Policy differences detected - review required
```
Exit code: `1` - Review required

**Next steps when changes detected:**
1. Run individual platform scripts to get detailed information
2. Extract detailed comparison data using the comparison functions
3. Analyze policy changes in depth
4. Assess security implications of new permissions
5. Evaluate upgrade complexity based on IAM/WIF changes
6. Generate prioritized update action plan
7. Provide go/no-go recommendation with security justification
