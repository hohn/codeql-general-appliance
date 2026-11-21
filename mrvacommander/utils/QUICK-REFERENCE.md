# Quick Reference Card

## Create a PR (no gh/enterprise-gh needed)

### Browser Method (Simplest)
```bash
cd ~/c/example/psa-mrva/mrvacommander/utils
./create-pr-browser.sh OWNER/REPO HEAD_BRANCH BASE_BRANCH "Title" "Body"
```

### API Method (Automated)
```bash
export GHE_TOKEN='your-token-here'
./create-pr-with-curl.sh OWNER/REPO HEAD_BRANCH BASE_BRANCH "Title" "Body"
```

### Examples
```bash
# Browser
./create-pr-browser.sh PSA-MRVA/server-commander \
    feature-branch main "Add feature"

# API (fully automated)
export GHE_TOKEN='ghp_...'
./create-pr-with-curl.sh PSA-MRVA/server-commander \
    feature-branch main "Add feature" "Description here"
```

---

## Bump MRVA Versions

### Interactive (Most Control)
```bash
./bump-version-interactive.sh v0.6.0 main
# Prompts at every step, validates builds
```

### Semi-Automated (Balanced)
```bash
./manual-bump-version.sh v0.6.0 main
# Confirms at major decision points
```

### Reference (Copy Commands)
```bash
cat manual-bump-reference.sh
# Don't run - copy individual commands
```

---

## Fix enterprise-gh 404 Error

Replace in `bump-mrvacommander-version.sh` line ~138:

```bash
# OLD:
enterprise-gh create-pr --title "$PR_TITLE" ...

# NEW (browser):
./utils/create-pr-browser.sh "PSA-MRVA/$TARGET_DIR" \
    "$BRANCH_NAME" "$MRVA_BRANCH" "$PR_TITLE" "$DESCRIPTION"

# OR (curl):
export GHE_TOKEN='token'
./utils/create-pr-with-curl.sh "PSA-MRVA/$TARGET_DIR" \
    "$BRANCH_NAME" "$MRVA_BRANCH" "$PR_TITLE" "$DESCRIPTION"
```

---

## Test PR Creation

```bash
./test-pr-creation.sh PSA-MRVA/server-commander main
```

---

## Environment Setup

```bash
# For Go modules (always needed)
export GOPRIVATE="*.dev.example.com"
export GOPROXY="https://goproxy.dev.example.com,direct"

# For curl PR creation (optional)
export GHE_TOKEN='ghp_your_token_here'

# Get token from:
# https://github.dev.example.com/settings/tokens
```

---

## Common Commands

### Manual Version Bump Workflow
```bash
# 1. mrvacommander
cd ~/mrva/mrvacommander
export GOPRIVATE="*.dev.example.com"
export GOPROXY="https://goproxy.dev.example.com,direct"
go clean -modcache && rm go.sum && go mod tidy
git tag v0.6.0
git push psa && git push --tags psa

# 2. server-commander
cd ~/c/example/psa-mrva/server-commander
# Edit go.mod - update mrvacommander version
go clean -modcache && rm go.sum && go mod tidy
go build .
git commit -am "update dependency tag in go.mod"
git tag v0.6.0
git push --tags psa main

# 3. agent-commander-argo
cd ~/c/example/psa-mrva/agent-commander-argo
# Edit go.mod - update mrvacommander version
go clean -modcache && rm go.sum && go mod tidy
go build .
git commit -am "update dependency tag in go.mod"
git tag v0.6.0
git push --tags psa main
```

### Update go.mod with sed
```bash
NEW_VERSION="v0.6.0"
sed -i.bak -E "s|(github\.dev\.example\.com/PSA-MRVA/mrvacommander )v[0-9]+\.[0-9]+\.[0-9]+(-[^ ]*)?|\1${NEW_VERSION}|" go.mod
rm go.mod.bak
```

---

## Troubleshooting

### 404 Not Found (PR creation)
- Check repository name (case-sensitive)
- Verify branch is pushed: `git push origin branch-name`
- Check branch exists: `git ls-remote --heads origin`

### 401 Unauthorized (curl)
- Check token: `echo $GHE_TOKEN`
- Verify token has `repo` scope
- Check expiration

### 422 Validation Failed
- PR already exists for branch
- No commits between head and base
- Base branch doesn't exist

### go mod tidy failed
- Check VPN connection
- Verify GOPRIVATE and GOPROXY set
- Run `go clean -modcache`

---

## File Locations

```
~/c/example/psa-mrva/mrvacommander/
├── bump-mrvacommander-version.sh    # Original automated script
└── utils/
    ├── create-pr-browser.sh         # PR via browser
    ├── create-pr-with-curl.sh       # PR via API
    ├── bump-version-interactive.sh  # Interactive bump
    ├── manual-bump-version.sh       # Semi-automated bump
    ├── manual-bump-reference.sh     # Reference/checklist
    └── test-pr-creation.sh          # Test PR methods
```

---

## Decision Tree

**Need to create a PR?**
- Want automation? → Use `create-pr-with-curl.sh` (need token)
- Want simplicity? → Use `create-pr-browser.sh` (no token)

**Need to bump versions?**
- Learning process? → Use `bump-version-interactive.sh`
- Know the process? → Use `manual-bump-version.sh`
- Want reference? → Use `manual-bump-reference.sh`

**Need to fix enterprise-gh?**
- See `fix-bump-script-pr-creation.md`
- Or use browser/curl methods instead

---

## One-Liners

```bash
# Create PR via browser
./create-pr-browser.sh PSA-MRVA/server-commander feature main "Title"

# Create PR via API
GHE_TOKEN=xxx ./create-pr-with-curl.sh PSA-MRVA/server-commander feature main "Title"

# Bump version interactively
./bump-version-interactive.sh v0.6.0 main

# Bump version semi-automated
./manual-bump-version.sh v0.6.0 main

# Test PR creation
./test-pr-creation.sh
```

---

## URLs

- **Get Token**: https://github.dev.example.com/settings/tokens
- **Repo**: https://github.dev.example.com/PSA-MRVA/server-commander
- **Create PR Manually**: `https://github.dev.example.com/OWNER/REPO/compare/BASE...HEAD`

---

## Full Documentation

- `README.md` - Main documentation
- `CREATE-PR-WITHOUT-GH.md` - PR creation guide
- `VERSION-BUMP-SCRIPTS.md` - Version bump comparison
- `fix-bump-script-pr-creation.md` - Fix enterprise-gh 404

---

*Keep this file handy for quick reference!*
