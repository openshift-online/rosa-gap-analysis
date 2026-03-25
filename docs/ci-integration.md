# CI/CD Integration

Integrate gap analysis into CI/CD pipelines.

## Key Points

- **Exit 0** on successful execution (regardless of differences)
- **Exit 1** only on execution failures
- Use output parsing or JSON reports to detect changes

## Detecting Differences

### Method 1: Parse Output

```bash
#!/bin/bash
if ./scripts/gap-all.sh 2>&1 | grep -q "differences detected"; then
  echo "Changes detected - review reports/"
fi
```

### Method 2: Parse JSON

```bash
#!/bin/bash
python3 ./scripts/gap-aws-sts.py --baseline 4.21 --target 4.22

added=$(jq '.comparison.actions.target_only | length' reports/gap-analysis-aws-sts_*.json)
if [ "$added" -gt 0 ]; then
  echo "New permissions: $added"
fi
```

## GitHub Actions

```yaml
name: Gap Analysis

on:
  schedule:
    - cron: '0 6 * * *'

jobs:
  gap-analysis:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          curl -L https://mirror.openshift.com/pub/openshift-v4/clients/ocp/stable/openshift-client-linux.tar.gz | tar xz -C /usr/local/bin

      - name: Run gap analysis
        run: ./scripts/gap-all.sh

      - name: Upload reports
        uses: actions/upload-artifact@v3
        with:
          name: gap-reports
          path: reports/
```

## GitLab CI

```yaml
gap-analysis:
  stage: test
  image: registry.access.redhat.com/ubi9/ubi:latest
  before_script:
    - dnf install -y python3 python3-pip curl
    - pip3 install -r requirements.txt
    - curl -L https://mirror.openshift.com/pub/openshift-v4/clients/ocp/stable/openshift-client-linux.tar.gz | tar xz -C /usr/local/bin
  script:
    - ./scripts/gap-all.sh
  artifacts:
    paths:
      - reports/
    expire_in: 30 days
```

## OpenShift CI (Prow)

```yaml
tests:
- as: gap-analysis
  commands: |
    gap-all.sh --baseline 4.21 --target 4.22
    cp reports/* ${ARTIFACT_DIR}/
  container:
    from: src
```

## Jenkins

```groovy
pipeline {
    agent any
    stages {
        stage('Gap Analysis') {
            steps {
                sh './scripts/gap-all.sh'
                archiveArtifacts artifacts: 'reports/**/*'
            }
        }
    }
}
```

## Report Archiving

```bash
# GitHub Actions / GitLab CI
REPORT_DIR=${ARTIFACT_DIR}/gap-reports ./scripts/gap-all.sh

# Upload to S3
aws s3 sync reports/ s3://bucket/gap-analysis/$(date +%Y%m%d)/

# Upload to GCS
gsutil -m rsync -r reports/ gs://bucket/gap-analysis/$(date +%Y%m%d)/
```

## Notifications

### Slack

```bash
#!/bin/bash
if ./scripts/gap-all.sh 2>&1 | grep -q "differences detected"; then
  curl -X POST -H 'Content-type: application/json' \
    --data '{"text":"Policy changes detected"}' \
    "$SLACK_WEBHOOK"
fi
```

### Email

```bash
#!/bin/bash
./scripts/gap-all.sh

# Attach reports
echo "See attached reports" | \
  mail -s "Gap Analysis Report" \
  -A reports/gap-analysis-full_*.md \
  team@example.com
```

## Best Practices

1. **Run on schedule** - Daily gap analysis against nightly builds
2. **Archive reports** - Save as CI artifacts for historical tracking
3. **Pin versions** - Use specific versions for reproducibility
4. **Conditional execution** - Only run when relevant files change
5. **Retain reports** - Keep for 30+ days for trend analysis

## Troubleshooting

```bash
# Verify tools
oc version --client
python3 --version
python3 -c "import yaml, jinja2"

# Increase timeout
export OC_CLIENT_TIMEOUT=300

# Ensure writable directories (OpenShift CI)
chmod 777 /tmp/gap-analysis-data
```
