# Fixing PR Creation in bump-mrvacommander-version.sh

The `enterprise-gh create-pr` command currently fails with 404 errors. Here's how to replace it.

## The Problem

Current code (line 138 in bump-mrvacommander-version.sh):
```bash
PATH=$DDD_PATH LD_LIBRARY_PATH=$DDD_LD_LIBRARY_PATH \
    enterprise-gh create-pr \
        --title "$PR_TITLE" \
        --body "$DESCRIPTION" \
        "PSA-MRVA/$TARGET_DIR:$BRANCH_NAME" \
        "PSA-MRVA/$TARGET_DIR:$MRVA_BRANCH"

# Returns: 404 Not Found
```

## Solution 1: Browser Method (Interactive)

Replace with browser URL approach - opens browser for manual creation:

```bash
# Replace the enterprise-gh line with:
"$(dirname "$0")/utils/create-pr-browser.sh" \
    "PSA-MRVA/$TARGET_DIR" \
    "$BRANCH_NAME" \
    "$MRVA_BRANCH" \
    "$PR_TITLE" \
    "$DESCRIPTION"
```

**Pros:**
- No authentication needed
- Works immediately
- Visual confirmation

**Cons:**
- Requires manual click in browser
- Not fully automated

## Solution 2: curl Method (Fully Automated)

Replace with direct API call - fully automated:

```bash
# Set token first (add near top of script):
if [[ -z "${GHE_TOKEN:-}" ]]; then
    echo "Error: GHE_TOKEN environment variable not set"
    echo "Export your GitHub Enterprise personal access token:"
    echo "  export GHE_TOKEN='your-token-here'"
    exit 1
fi

# Replace the enterprise-gh line with:
"$(dirname "$0")/utils/create-pr-with-curl.sh" \
    "PSA-MRVA/$TARGET_DIR" \
    "$BRANCH_NAME" \
    "$MRVA_BRANCH" \
    "$PR_TITLE" \
    "$DESCRIPTION"
```

**Pros:**
- Fully automated
- Returns PR URL immediately
- No browser needed

**Cons:**
- Requires personal access token
- Token must be secured

## Solution 3: Hybrid (Browser as Fallback)

Try enterprise-gh first, fall back to browser if it fails:

```bash
# Try enterprise-gh first
if ! PATH=$DDD_PATH LD_LIBRARY_PATH=$DDD_LD_LIBRARY_PATH \
    enterprise-gh create-pr \
        --title "$PR_TITLE" \
        --body "$DESCRIPTION" \
        "PSA-MRVA/$TARGET_DIR:$BRANCH_NAME" \
        "PSA-MRVA/$TARGET_DIR:$MRVA_BRANCH"; then

    echo "enterprise-gh failed, opening browser instead..."
    "$(dirname "$0")/utils/create-pr-browser.sh" \
        "PSA-MRVA/$TARGET_DIR" \
        "$BRANCH_NAME" \
        "$MRVA_BRANCH" \
        "$PR_TITLE" \
        "$DESCRIPTION"
fi
```

## Recommended Approach

For now, use **Solution 1 (Browser)** because:
- ✅ Simplest to implement
- ✅ No new dependencies (no token needed)
- ✅ Works reliably
- ✅ User can review before creating PR

When you're ready for full automation, switch to **Solution 2 (curl)**.

## Complete Patch

Here's the exact change to make to `bump-mrvacommander-version.sh`:

### Find (around line 138):

```bash
    PATH=$DDD_PATH LD_LIBRARY_PATH=$DDD_LD_LIBRARY_PATH enterprise-gh create-pr --title "$PR_TITLE" --body "$DESCRIPTION" "PSA-MRVA/$TARGET_DIR:$BRANCH_NAME" "PSA-MRVA/$TARGET_DIR:$MRVA_BRANCH"
```

### Replace with:

```bash
    # Create PR using browser method (since enterprise-gh has 404 errors)
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    "$SCRIPT_DIR/utils/create-pr-browser.sh" \
        "PSA-MRVA/$TARGET_DIR" \
        "$BRANCH_NAME" \
        "$MRVA_BRANCH" \
        "$PR_TITLE" \
        "$DESCRIPTION"
```

## Testing the Fix

```bash
cd ~/c/example/psa-mrva/mrvacommander

# Test with browser method
./bump-mrvacommander-version.sh mh-doc-version-2

# When it gets to PR creation, browser should open
# with pre-filled PR form
```

## Alternative: Skip PR Creation Entirely

If you want to create PRs manually later:

```bash
# Comment out or skip the PR creation:
# PATH=$DDD_PATH LD_LIBRARY_PATH=$DDD_LD_LIBRARY_PATH enterprise-gh create-pr ...
echo "Skipping PR creation - create manually at:"
echo "  https://github.dev.example.com/PSA-MRVA/$TARGET_DIR/compare/$MRVA_BRANCH...$BRANCH_NAME"
```

## Manual PR Creation After Script Runs

If the script completes without creating PRs, create them manually:

```bash
# For server-commander
cd ~/c/example/psa-mrva/mrvacommander/utils
./create-pr-browser.sh \
    PSA-MRVA/server-commander \
    mrva_commander_bump_to_v0.6.0 \
    mh-doc-version-2 \
    "Bump mrvacommander to v0.6.0"

# For agent-commander-argo
./create-pr-browser.sh \
    PSA-MRVA/agent-commander-argo \
    mrva_commander_bump_to_v0.6.0 \
    mh-doc-version-2 \
    "Bump mrvacommander to v0.6.0"
```

## Using curl Method (Advanced)

If you prefer full automation:

### 1. Set up token

```bash
# Get token from https://github.dev.example.com/settings/tokens
export GHE_TOKEN='ghp_your_token_here'

# Or store in your shell profile
echo 'export GHE_TOKEN="ghp_your_token_here"' >> ~/.bashrc
```

### 2. Modify script

```bash
# Near top of bump-mrvacommander-version.sh, after set -x:

# Check for GHE_TOKEN if we'll need it for PR creation
if [[ -z "${GHE_TOKEN:-}" ]]; then
    echo "Warning: GHE_TOKEN not set. PR creation will fail."
    echo "Set it with: export GHE_TOKEN='your-token-here'"
    read -p "Continue anyway? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi
```

```bash
# Around line 138, replace enterprise-gh with:

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
"$SCRIPT_DIR/utils/create-pr-with-curl.sh" \
    "PSA-MRVA/$TARGET_DIR" \
    "$BRANCH_NAME" \
    "$MRVA_BRANCH" \
    "$PR_TITLE" \
    "$DESCRIPTION"
```

## Comparison

| Method | Auto? | Token? | User Action |
|--------|-------|--------|-------------|
| enterprise-gh (broken) | Yes | Yes | None |
| Browser | No | No | Click "Create PR" |
| curl | Yes | Yes | None |

## My Recommendation

1. **Short term**: Use browser method
   - Works immediately
   - No setup needed
   - Just one extra click

2. **Long term**: Fix enterprise-gh OR switch to curl
   - Investigate why enterprise-gh returns 404
   - Or set up GHE_TOKEN and use curl permanently
