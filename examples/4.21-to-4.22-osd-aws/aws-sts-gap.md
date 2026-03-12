# AWS STS Policy Gap Analysis Report

**Baseline**: 4.21
**Target**: 4.22
**Platform**: aws
**Generated**: 2026-03-10 12:00:00

---

## Summary

- **Total gaps found**: 8
- **Added**: 5
- **Removed**: 1
- **Changed**: 2

---

## Detailed Findings

### Added Permissions
> New IAM permissions required in the target version

#### 1. EC2 Instance Connect Endpoint Permission
**Action**: `ec2:CreateInstanceConnectEndpoint`
**Resource**: `arn:aws:ec2:*:*:instance-connect-endpoint/*`
**Reason**: Required for new EC2 Instance Connect feature in OpenShift 4.22

**Impact**: Medium
- Enables secure SSH access to cluster nodes without bastion hosts
- Required for debugging and troubleshooting features

#### 2. EBS Snapshot Archive Permissions
**Actions**:
- `ec2:ArchiveSnapshot`
- `ec2:RestoreSnapshot`

**Resource**: `arn:aws:ec2:*:*:snapshot/*`
**Reason**: Support for EBS snapshot archiving in storage classes

**Impact**: Low
- Optional feature for long-term backup retention
- Cost optimization capability

#### 3. VPC Lattice Permissions (Preview)
**Actions**:
- `vpc-lattice:CreateService`
- `vpc-lattice:DeleteService`
- `vpc-lattice:ListServices`

**Resource**: `*`
**Reason**: Preview support for AWS VPC Lattice service networking

**Impact**: Low
- Preview feature, not enabled by default
- Required only if using VPC Lattice integration

### Removed Permissions
> Permissions no longer required in the target version

#### 1. Classic Load Balancer Permissions
**Action**: `elasticloadbalancing:CreateLoadBalancer`
**Resource**: Classic Load Balancers only
**Reason**: Full migration to Network/Application Load Balancers complete

**Impact**: Medium
- Cleanup of legacy permissions
- No functional impact (NLB/ALB still supported)

### Changed Permissions
> Permissions with modified scopes or conditions

#### 1. S3 Bucket Access Scope Narrowed
**Before**:
```json
{
  "Effect": "Allow",
  "Action": "s3:*",
  "Resource": "*"
}
```

**After**:
```json
{
  "Effect": "Allow",
  "Action": [
    "s3:GetObject",
    "s3:PutObject",
    "s3:DeleteObject"
  ],
  "Resource": "arn:aws:s3:::openshift-*/*"
}
```

**Reason**: Security hardening - principle of least privilege
**Impact**: High
- **ACTION REQUIRED**: Verify S3 bucket naming follows `openshift-*` pattern
- Improved security posture
- May require bucket renaming for existing clusters

#### 2. KMS Key Permissions - Added Condition
**Before**: No conditions
**After**: Added condition:
```json
{
  "Condition": {
    "StringEquals": {
      "kms:ViaService": [
        "ec2.*.amazonaws.com",
        "s3.*.amazonaws.com"
      ]
    }
  }
}
```

**Reason**: Restrict KMS key usage to specific AWS services
**Impact**: Medium
- Enhanced security
- No functional impact for standard deployments

---

## Security Implications

### Positive Changes
1. ✅ S3 permissions narrowed to specific actions and resources
2. ✅ KMS key usage restricted to authorized services
3. ✅ Removal of unused Classic ELB permissions

### Permissions Requiring Review
1. ⚠️ VPC Lattice permissions use wildcard resources (preview feature)
2. ⚠️ Instance Connect permissions enable SSH access (review security posture)

---

## Recommendations

### Before Upgrade

1. **Update IAM Roles/Policies**
   ```bash
   # Update installer role
   aws iam put-role-policy --role-name openshift-installer \
     --policy-name openshift-installer-policy \
     --policy-document file://new-policy.json

   # Update worker node instance profile
   aws iam put-role-policy --role-name openshift-worker \
     --policy-name openshift-worker-policy \
     --policy-document file://new-worker-policy.json
   ```

2. **Verify S3 Bucket Naming**
   ```bash
   # List all S3 buckets used by cluster
   aws s3 ls | grep -E 'openshift-.*'

   # Rename buckets if needed
   aws s3 mb s3://openshift-cluster-abc-registry
   aws s3 sync s3://old-registry-bucket s3://openshift-cluster-abc-registry
   ```

3. **Test in Non-Production**
   - Deploy test cluster with new IAM policies
   - Verify all cluster operators are functional
   - Test EC2 Instance Connect feature

### During Upgrade

- Monitor CloudTrail for IAM permission denied errors
- Have rollback plan ready

### After Upgrade

1. **Validate New Features**
   ```bash
   # Test Instance Connect
   oc debug node/worker-0

   # Verify snapshot archiving works
   oc get volumesnapshotclass
   ```

2. **Security Audit**
   - Review IAM policies in production
   - Verify least-privilege principles
   - Document VPC Lattice usage (if enabled)

---

## Impact Assessment

| Change | Customer Impact | Required Action | Priority |
|--------|----------------|-----------------|----------|
| S3 scope narrowing | High | Verify bucket naming | **P0** |
| Instance Connect | Medium | Review security policy | P1 |
| KMS conditions | Low | None (automatic) | P2 |
| ELB cleanup | None | None (cleanup) | P3 |
| VPC Lattice | None | None (preview) | P3 |

---

## Raw Data

**Baseline Policy**: `data/4.21-osd-aws-sts.json`
**Target Policy**: `data/4.22-osd-aws-sts.json`

---

## References

- [AWS STS Documentation](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_temp.html)
- [OpenShift on AWS Prerequisites](https://docs.openshift.com/container-platform/4.22/installing/installing_aws/installing-aws-account.html)
- [IAM Policy Simulator](https://policysim.aws.amazon.com/)
