# Creating GitHub PRs Without gh/enterprise-gh

Yes, you can create PRs from the command line without `gh` or `enterprise-gh` using these methods.

## Methods Comparison

| Method | Auth Required | Complexity | Automated | Best For |
|--------|--------------|------------|-----------|----------|
| **Browser URL** | No | Simple | No | Quick manual PRs |
| **curl + API** | Yes (token) | Medium | Yes | Scripted automation |
| **git + browser** | No | Simple | No | One-off PRs |

## Method 1: Browser URL (Simplest)

**Script:** `create-pr-browser.sh`

Opens your browser with PR fields pre-filled. No authentication needed.

### Usage

```bash
./create-pr-browser.sh PSA-MRVA/server-commander \
    mrva_commander_bump_to_v0.6.0 \
    mh-doc-version-2 \
    "Bump mrvacommander to v0.6.0" \
    "Updates dependency to latest version"
```

### How it works

Constructs a URL like:
```
https://github.dev.example.com/PSA-MRVA/server-commander/compare/mh-doc-version-2...mrva_commander_bump_to_v0.6.0?quick_pull=1&title=Bump...&body=Updates...
```

The browser opens with the PR creation form pre-filled. You click "Create Pull Request" to finish.

### Pros
- ✅ No authentication required
- ✅ Simple, just opens a browser
- ✅ Works immediately
- ✅ Visual confirmation before creating

### Cons
- ❌ Not fully automated (requires browser click)
- ❌ Can't be used in headless scripts

---

## Method 2: curl + GitHub API (Most Powerful)

**Script:** `create-pr-with-curl.sh`

Uses GitHub's REST API directly with curl. Fully automated.

### Setup

First, create a personal access token:

1. Go to https://github.dev.example.com/settings/tokens
2. Click "Generate new token"
3. Select scopes: `repo` (full control)
4. Generate and copy the token

```bash
export GHE_TOKEN='ghp_your_token_here'
```

### Usage

```bash
export GHE_TOKEN='your-token-here'

./create-pr-with-curl.sh PSA-MRVA/server-commander \
    mrva_commander_bump_to_v0.6.0 \
    mh-doc-version-2 \
    "Bump mrvacommander to v0.6.0" \
    "Updates dependency to latest version"
```

### How it works

Makes an HTTP POST to GitHub API:
```bash
curl -X POST \
    -H "Authorization: token ${GHE_TOKEN}" \
    -H "Accept: application/vnd.github.v3+json" \
    -d '{"title":"...","body":"...","head":"...","base":"..."}' \
    https://api.github.dev.example.com/repos/PSA-MRVA/server-commander/pulls
```

### Pros
- ✅ Fully automated
- ✅ Can be used in scripts
- ✅ No browser required
- ✅ Returns PR URL immediately

### Cons
- ❌ Requires personal access token
- ❌ Token needs to be secured
- ❌ More complex error handling

---

## Method 3: Manual Git URL (Simplest, No Script)

After pushing your branch, git often shows:

```
remote: Create a pull request for 'feature-branch' on GitHub by visiting:
remote:   https://github.dev.example.com/PSA-MRVA/server-commander/pull/new/feature-branch
```

Just click or paste that URL into your browser.

### Manually construct the URL

```bash
# Push your branch
git push origin feature-branch

# Construct URL manually
OWNER="PSA-MRVA"
REPO="server-commander"
BRANCH="feature-branch"

echo "https://github.dev.example.com/${OWNER}/${REPO}/pull/new/${BRANCH}"
```

---

## Integration with Version Bump Scripts

### Option 1: Browser URL in interactive script

Add to `bump-version-interactive.sh`:

```bash
# After pushing the branch
echo
info "Create PR via browser? [y/N]"
read -r response
case "$response" in
    [yY][eE][sS]|[yY])
        ./utils/create-pr-browser.sh \
            "PSA-MRVA/server-commander" \
            "$BRANCH_NAME" \
            "$MRVA_BRANCH" \
            "$PR_TITLE" \
            "$DESCRIPTION"
        ;;
esac
```

### Option 2: curl API in automated script

Replace `enterprise-gh create-pr` in `bump-mrvacommander-version.sh`:

```bash
# OLD (broken):
enterprise-gh create-pr --title "$PR_TITLE" --body "$DESCRIPTION" \
    "PSA-MRVA/$TARGET_DIR:$BRANCH_NAME" \
    "PSA-MRVA/$TARGET_DIR:$MRVA_BRANCH"

# NEW (works):
./utils/create-pr-with-curl.sh \
    "PSA-MRVA/$TARGET_DIR" \
    "$BRANCH_NAME" \
    "$MRVA_BRANCH" \
    "$PR_TITLE" \
    "$DESCRIPTION"
```

---

## Complete Example: Manual PR Creation

```bash
# 1. Push your branch
cd ~/c/example/psa-mrva/server-commander
git checkout -b update-dependencies
# ... make changes ...
git commit -am "Update dependencies"
git push origin update-dependencies

# 2. Create PR using browser method (no auth needed)
cd ~/c/example/psa-mrva/mrvacommander/utils
./create-pr-browser.sh \
    PSA-MRVA/server-commander \
    update-dependencies \
    main \
    "Update dependencies" \
    "This PR updates all Go dependencies to latest versions"

# Browser opens, click "Create Pull Request"
```

Or with curl method (fully automated):

```bash
# 1. Push your branch (same as above)
git push origin update-dependencies

# 2. Create PR using API (requires token)
export GHE_TOKEN='your-token-here'

./create-pr-with-curl.sh \
    PSA-MRVA/server-commander \
    update-dependencies \
    main \
    "Update dependencies" \
    "This PR updates all Go dependencies to latest versions"

# PR created, URL printed to console
```

---

## GitHub API Reference

### Create a Pull Request

**Endpoint:**
```
POST /repos/{owner}/{repo}/pulls
```

**Request:**
```json
{
  "title": "Amazing new feature",
  "body": "Please review this feature",
  "head": "feature-branch",
  "base": "main"
}
```

**Response (201 Created):**
```json
{
  "id": 1,
  "number": 123,
  "state": "open",
  "title": "Amazing new feature",
  "html_url": "https://github.dev.example.com/owner/repo/pull/123",
  ...
}
```

### Common Error Codes

| Code | Meaning | Solution |
|------|---------|----------|
| 401 | Unauthorized | Check token |
| 404 | Not found | Verify repo/branch names |
| 422 | Validation failed | PR already exists or no commits |

---

## Token Security

### Store token securely

**Option 1: Environment variable in shell profile**
```bash
# Add to ~/.bashrc or ~/.zshrc
export GHE_TOKEN='your-token-here'
```

**Option 2: macOS Keychain**
```bash
# Store
security add-generic-password -a ${USER} -s ghe_token -w

# Retrieve
export GHE_TOKEN=$(security find-generic-password -a ${USER} -s ghe_token -w)
```

**Option 3: File with restricted permissions**
```bash
echo 'export GHE_TOKEN="your-token"' > ~/.ghe_token
chmod 600 ~/.ghe_token
source ~/.ghe_token
```

### Never commit tokens!

Add to `.gitignore`:
```
.ghe_token
*token*
*.env
```

---

## URL Format Reference

### PR Creation URL Pattern

```
https://{github-host}/{owner}/{repo}/compare/{base}...{head}?quick_pull=1&title={title}&body={body}
```

**Example:**
```
https://github.dev.example.com/PSA-MRVA/server-commander/compare/main...feature-branch?quick_pull=1&title=My+Feature&body=Description+here
```

### Query Parameters

- `quick_pull=1` - Opens PR creation form directly
- `title=...` - Pre-fills title (URL encoded)
- `body=...` - Pre-fills description (URL encoded)
- `labels=bug,enhancement` - Pre-selects labels
- `assignees=username` - Pre-assigns reviewers

---

## Comparison with enterprise-gh

### What enterprise-gh does

```bash
enterprise-gh create-pr \
    --title "My PR" \
    --body "Description" \
    owner/repo:feature-branch \
    owner/repo:main
```

### Equivalent with curl

```bash
./create-pr-with-curl.sh \
    owner/repo \
    feature-branch \
    main \
    "My PR" \
    "Description"
```

### Equivalent with browser

```bash
./create-pr-browser.sh \
    owner/repo \
    feature-branch \
    main \
    "My PR" \
    "Description"
```

---

## When to Use Each Method

### Use Browser Method (`create-pr-browser.sh`) when:
- ✅ Creating one-off PRs manually
- ✅ You don't have/want API tokens
- ✅ You want to review fields before creating
- ✅ You need to set additional options (labels, reviewers)

### Use curl Method (`create-pr-with-curl.sh`) when:
- ✅ Automating PR creation in scripts
- ✅ Creating many PRs programmatically
- ✅ Running in CI/CD or cron jobs
- ✅ You have a personal access token

### Use enterprise-gh when:
- ✅ You have it working (not broken like now)
- ✅ You need additional enterprise-gh features
- ✅ Your organization requires it

---

## Testing

### Test browser method

```bash
cd ~/c/example/psa-mrva/mrvacommander/utils
./create-pr-browser.sh \
    PSA-MRVA/server-commander \
    test-branch \
    main \
    "Test PR" \
    "This is a test"

# Should open browser with pre-filled form
```

### Test curl method

```bash
export GHE_TOKEN='your-token-here'

./create-pr-with-curl.sh \
    PSA-MRVA/server-commander \
    test-branch \
    main \
    "Test PR" \
    "This is a test"

# Should create PR and print URL
```

---

## Troubleshooting

### "404 Not Found"

**Check:**
- Repository name is correct (case-sensitive)
- Branch exists on remote: `git ls-remote --heads origin | grep branch-name`
- You have access to the repository

### "422 Validation Failed"

**Common causes:**
- PR already exists for this branch
- Head branch has no commits
- Base branch doesn't exist
- No difference between head and base

**Check:**
```bash
# See if PR exists
curl -H "Authorization: token $GHE_TOKEN" \
    "https://api.github.dev.example.com/repos/PSA-MRVA/server-commander/pulls?head=feature-branch"

# Check commits between branches
git log base-branch..head-branch
```

### "401 Unauthorized"

**Check:**
- Token is set: `echo $GHE_TOKEN`
- Token has `repo` scope
- Token hasn't expired

### Browser doesn't open

**Manual workaround:**
```bash
# The script prints the URL
# Copy and paste into browser manually
```

---

## Summary

**Answer to your question:** Yes, PRs can be created without `gh`/`enterprise-gh` using:

1. **Browser URL** - Simplest, no auth, opens browser
2. **curl + API** - Fully automated, requires token
3. **Manual git URL** - No script needed, copy from git output

I've created both scripts for you in `utils/`. Choose based on your needs!
