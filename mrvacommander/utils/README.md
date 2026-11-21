# MRVA Version Bump Utilities

Utility scripts for bumping MRVA component versions and creating PRs.

## Quick Start

### Create a PR without gh/enterprise-gh

**Method 1: Browser (simplest)**
```bash
./create-pr-browser.sh PSA-MRVA/server-commander feature-branch main "My PR Title"
# Opens browser with pre-filled PR form
```

**Method 2: API (fully automated)**
```bash
export GHE_TOKEN='your-token-here'
./create-pr-with-curl.sh PSA-MRVA/server-commander feature-branch main "My PR Title"
# Creates PR immediately, returns URL
```

### Bump versions interactively

```bash
./bump-version-interactive.sh v0.6.0 main
# Prompts at each step, validates builds
```

### Bump versions semi-automated

```bash
./manual-bump-version.sh v0.6.0 main
# Automates tedious parts, confirms major steps
```

## Scripts

### PR Creation

| Script | Purpose | Auth Required |
|--------|---------|---------------|
| `create-pr-browser.sh` | Opens browser with pre-filled PR | No |
| `create-pr-with-curl.sh` | Creates PR via API (fully automated) | Yes (token) |
| `test-pr-creation.sh` | Tests both PR creation methods | Optional |

### Version Bumping

| Script | Purpose | Interaction |
|--------|---------|-------------|
| `bump-version-interactive.sh` | Interactive version bump | High (prompts) |
| `manual-bump-version.sh` | Semi-automated version bump | Medium |
| `manual-bump-reference.sh` | Reference/checklist (don't run) | None |

## Documentation

| File | Content |
|------|---------|
| `CREATE-PR-WITHOUT-GH.md` | Complete guide to PR creation methods |
| `fix-bump-script-pr-creation.md` | How to fix enterprise-gh 404 error |
| `VERSION-BUMP-SCRIPTS.md` | Version bump workflow guide |

## Examples

### Example 1: Create PR with Browser

```bash
# Push your branch first
git push origin my-feature-branch

# Create PR via browser
./create-pr-browser.sh \
    PSA-MRVA/server-commander \
    my-feature-branch \
    main \
    "Add new feature" \
    "This adds the requested feature with tests"

# Browser opens, click "Create Pull Request"
```

### Example 2: Create PR with curl (Automated)

```bash
# Get token from: https://github.dev.example.com/settings/tokens
export GHE_TOKEN='ghp_your_token_here'

# Push your branch
git push origin my-feature-branch

# Create PR automatically
./create-pr-with-curl.sh \
    PSA-MRVA/server-commander \
    my-feature-branch \
    main \
    "Add new feature" \
    "This adds the requested feature with tests"

# PR created, URL printed
```

### Example 3: Bump Version Interactively

```bash
./bump-version-interactive.sh v0.6.0 main

# Prompts:
# ? Ready to proceed? [y/N] y
# ? Clean and tidy mrvacommander? [y/N] y
# ? Create tag v0.6.0 in mrvacommander? [y/N] y
# ? Push mrvacommander to psa remote? [y/N] y
# ... continues for each component
```

### Example 4: Bump Version Semi-Automated

```bash
./manual-bump-version.sh v0.6.0 main

# Shows progress, confirms at major steps:
# - Tag mrvacommander? [y/N]
# - Commit/tag/push server-commander? [y/N]
# - Commit/tag/push agent-commander-argo? [y/N]
```

## Testing

Test PR creation methods:

```bash
./test-pr-creation.sh PSA-MRVA/server-commander main

# This will:
# 1. Create a test branch
# 2. Test browser method
# 3. Test curl method (if token set)
# 4. Clean up test branch
```

## Integration

### Fix enterprise-gh 404 Error

Replace this in `bump-mrvacommander-version.sh`:

```bash
# OLD (broken):
enterprise-gh create-pr --title "$PR_TITLE" --body "$DESCRIPTION" ...

# NEW (browser method):
./utils/create-pr-browser.sh \
    "PSA-MRVA/$TARGET_DIR" \
    "$BRANCH_NAME" \
    "$MRVA_BRANCH" \
    "$PR_TITLE" \
    "$DESCRIPTION"

# OR (curl method):
export GHE_TOKEN='your-token'
./utils/create-pr-with-curl.sh \
    "PSA-MRVA/$TARGET_DIR" \
    "$BRANCH_NAME" \
    "$MRVA_BRANCH" \
    "$PR_TITLE" \
    "$DESCRIPTION"
```

See `fix-bump-script-pr-creation.md` for detailed instructions.

## Directory Structure

```
utils/
├── README.md                          # This file
├── CREATE-PR-WITHOUT-GH.md            # PR creation guide
├── VERSION-BUMP-SCRIPTS.md            # Version bump guide
├── fix-bump-script-pr-creation.md     # Fix enterprise-gh 404 error
│
├── create-pr-browser.sh               # Create PR via browser
├── create-pr-with-curl.sh             # Create PR via API
├── test-pr-creation.sh                # Test PR creation
│
├── bump-version-interactive.sh        # Interactive version bump
├── manual-bump-version.sh             # Semi-automated bump
└── manual-bump-reference.sh           # Reference (don't run)
```

## Requirements

### All Scripts
- Bash
- Git configured for github

### Browser Method
- No special requirements
- Works on macOS, Linux, Windows

### curl Method
- Personal access token from https://github.dev.example.com/settings/tokens
- Token needs `repo` scope
- Export as: `export GHE_TOKEN='your-token'`

### Version Bump Scripts
- Go installed
- On VPN
- Access to internal packages
- Repositories cloned locally

## Environment Variables

```bash
# For curl PR creation
export GHE_TOKEN='ghp_your_token_here'

# For Go module dependencies
export GOPRIVATE="*.dev.example.com"
export GOPROXY="https://goproxy.dev.example.com,direct"

# Optional: Custom GitHub Enterprise URL
export GHE_URL='https://github.dev.example.com'
export GHE_API_URL='https://api.github.dev.example.com'
```

## Troubleshooting

### "404 Not Found" when creating PR

**Check:**
- Repository name is correct (case-sensitive)
- Branches exist on remote
- You pushed the branch: `git push origin branch-name`

### "401 Unauthorized" with curl method

**Check:**
- Token is set: `echo $GHE_TOKEN`
- Token has `repo` scope
- Token hasn't expired

### "422 Validation Failed"

**Common causes:**
- PR already exists for this branch
- No commits between branches
- Base branch doesn't exist

### Version bump "go mod tidy failed"

**Check:**
- On VPN
- GOPRIVATE and GOPROXY set
- Run `go clean -modcache` and retry

## Tips

### Secure Token Storage

**Option 1: Shell profile**
```bash
echo 'export GHE_TOKEN="your-token"' >> ~/.bashrc
```

**Option 2: macOS Keychain**
```bash
# Store
security add-generic-password -a ${USER} -s ghe_token -w

# Retrieve
export GHE_TOKEN=$(security find-generic-password -a ${USER} -s ghe_token -w)
```

**Option 3: Restricted file**
```bash
echo 'export GHE_TOKEN="your-token"' > ~/.ghe_token
chmod 600 ~/.ghe_token
source ~/.ghe_token
```

### Quick PR from Command Line

After pushing a branch, git shows:
```
remote: Create a pull request for 'branch-name' on GitHub by visiting:
remote:   https://github.dev.example.com/owner/repo/pull/new/branch-name
```

Just click that URL - no script needed!

## Which Script to Use?

### For PR Creation

**Use `create-pr-browser.sh` if:**
- ✅ One-off manual PRs
- ✅ Don't have/want API token
- ✅ Want to review before creating

**Use `create-pr-with-curl.sh` if:**
- ✅ Automating in scripts
- ✅ Creating many PRs
- ✅ Have personal access token

### For Version Bumps

**Use `bump-version-interactive.sh` if:**
- ✅ Learning the process
- ✅ Want to see each step
- ✅ Need to skip certain steps

**Use `manual-bump-version.sh` if:**
- ✅ Want automation with checkpoints
- ✅ Familiar with the process
- ✅ Want to specify version explicitly

**Use `manual-bump-reference.sh` if:**
- ✅ Want to run commands manually
- ✅ Need a reference/checklist
- ✅ Customizing the workflow

## Support

For questions or issues:

1. Check the documentation:
   - `CREATE-PR-WITHOUT-GH.md`
   - `VERSION-BUMP-SCRIPTS.md`
   - `fix-bump-script-pr-creation.md`

2. Test the scripts:
   - `./test-pr-creation.sh`

3. Review the reference:
   - `manual-bump-reference.sh` (checklist)

## Related

- Parent directory: `../` contains the original `bump-mrvacommander-version.sh`
- Documentation: `../VERSION-BUMP-SCRIPTS.md` for comparison of all methods
