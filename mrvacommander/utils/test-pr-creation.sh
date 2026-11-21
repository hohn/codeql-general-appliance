#!/bin/bash

# Test script for PR creation methods
# Creates a test branch and tries to create a PR using both methods

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info() { echo -e "${GREEN}ℹ${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
error() { echo -e "${RED}✗${NC} $*"; }

# ============================================================
# Configuration
# ============================================================

REPO="${1:-PSA-MRVA/server-commander}"
BASE_BRANCH="${2:-main}"
TEST_BRANCH="test-pr-creation-$(date +%Y%m%d%H%M%S)"

echo
echo "================================================"
echo "PR Creation Methods Test"
echo "================================================"
echo
info "Repository:   $REPO"
info "Base branch:  $BASE_BRANCH"
info "Test branch:  $TEST_BRANCH"
echo

# ============================================================
# Extract owner and repo name
# ============================================================

OWNER="${REPO%%/*}"
REPO_NAME="${REPO##*/}"

# ============================================================
# Determine local repo path
# ============================================================

# Try common locations
if [[ -d ~/c/example/psa-mrva/${REPO_NAME} ]]; then
    REPO_PATH=~/c/example/psa-mrva/${REPO_NAME}
elif [[ -d ~/mrva/${REPO_NAME} ]]; then
    REPO_PATH=~/mrva/${REPO_NAME}
else
    error "Repository not found locally"
    echo "  Tried: ~/c/example/psa-mrva/${REPO_NAME}"
    echo "  Tried: ~/mrva/${REPO_NAME}"
    exit 1
fi

info "Found repository at: $REPO_PATH"
echo

# ============================================================
# Create test branch
# ============================================================

cd "$REPO_PATH"

info "Current directory: $(pwd)"
echo

warn "This will create and push a test branch: $TEST_BRANCH"
read -r -p "Continue? [y/N] " response
case "$response" in
    [yY][eE][sS]|[yY]) ;;
    *) error "Aborted"; exit 0 ;;
esac

echo
info "Creating test branch..."

# Ensure we're on base branch
git fetch origin
git checkout "$BASE_BRANCH"
git pull origin "$BASE_BRANCH"

# Create test branch
git checkout -b "$TEST_BRANCH"

# Make a trivial change
echo "# Test PR created at $(date)" >> README.md
git add README.md
git commit -m "Test PR creation - safe to delete"

# Push to remote
git push origin "$TEST_BRANCH"

info "Test branch created and pushed"
echo

# ============================================================
# Test Method 1: Browser
# ============================================================

echo "================================================"
echo "Test 1: Browser Method"
echo "================================================"
echo

info "This will open your browser with a PR creation form"
read -r -p "Test browser method? [y/N] " response

if [[ "$response" =~ ^[Yy] ]]; then
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

    "$SCRIPT_DIR/create-pr-browser.sh" \
        "$REPO" \
        "$TEST_BRANCH" \
        "$BASE_BRANCH" \
        "[TEST] PR Creation Test" \
        "This is a test PR created by test-pr-creation.sh. Safe to close without merging."

    echo
    warn "Browser should have opened with PR creation form"
    warn "IMPORTANT: Do NOT actually create the PR - just close the browser tab"
    echo
    read -r -p "Press Enter when done reviewing..."
fi

# ============================================================
# Test Method 2: curl API
# ============================================================

echo
echo "================================================"
echo "Test 2: curl API Method"
echo "================================================"
echo

if [[ -z "${GHE_TOKEN:-}" ]]; then
    warn "GHE_TOKEN not set - skipping curl test"
    echo
    info "To test curl method:"
    echo "  1. Get token from: https://github.dev.example.com/settings/tokens"
    echo "  2. export GHE_TOKEN='your-token-here'"
    echo "  3. Run this script again"
else
    info "GHE_TOKEN is set"
    read -r -p "Test curl method? [y/N] " response

    if [[ "$response" =~ ^[Yy] ]]; then
        SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

        "$SCRIPT_DIR/create-pr-with-curl.sh" \
            "$REPO" \
            "$TEST_BRANCH" \
            "$BASE_BRANCH" \
            "[TEST] PR Creation Test - DELETE ME" \
            "This is a test PR created by test-pr-creation.sh. Please close this PR without merging."

        echo
        warn "A real PR was just created!"
        warn "You should see a PR URL above"
        echo
        info "Next steps:"
        echo "  1. Visit the PR URL"
        echo "  2. Verify it was created correctly"
        echo "  3. Close the PR (DO NOT MERGE)"
    fi
fi

# ============================================================
# Cleanup
# ============================================================

echo
echo "================================================"
echo "Cleanup"
echo "================================================"
echo

read -r -p "Delete test branch? [y/N] " response

if [[ "$response" =~ ^[Yy] ]]; then
    info "Cleaning up..."

    # Switch back to base branch
    git checkout "$BASE_BRANCH"

    # Delete local branch
    git branch -D "$TEST_BRANCH"

    # Delete remote branch
    git push origin --delete "$TEST_BRANCH"

    info "Test branch deleted"
else
    warn "Test branch NOT deleted: $TEST_BRANCH"
    echo
    info "To delete manually:"
    echo "  git checkout $BASE_BRANCH"
    echo "  git branch -D $TEST_BRANCH"
    echo "  git push origin --delete $TEST_BRANCH"
fi

echo
echo "================================================"
echo "Test Complete"
echo "================================================"
echo
info "Both PR creation methods are working if you saw:"
echo "  ✓ Browser opened with pre-filled PR form"
echo "  ✓ curl method returned a PR URL"
echo
info "You can now use these in your version bump scripts!"
