#!/bin/bash

# Open browser to create a GitHub PR with pre-filled fields
# Works without API tokens - just constructs a URL
#
# This is the simplest method - no authentication needed
# The URL will open the PR creation page with fields pre-filled
#
# Usage: ./create-pr-browser.sh <owner/repo> <head-branch> <base-branch> [title] [body]

set -euo pipefail

# ============================================================
# Parse arguments
# ============================================================

REPO="${1:-}"
HEAD_BRANCH="${2:-}"
BASE_BRANCH="${3:-}"
TITLE="${4:-}"
BODY="${5:-}"

if [[ -z "$REPO" ]] || [[ -z "$HEAD_BRANCH" ]] || [[ -z "$BASE_BRANCH" ]]; then
    echo "Usage: $0 <owner/repo> <head-branch> <base-branch> [title] [body]"
    echo
    echo "Arguments:"
    echo "  owner/repo    Repository (e.g., PSA-MRVA/server-commander)"
    echo "  head-branch   Source branch (your feature branch)"
    echo "  base-branch   Target branch (e.g., main, mh-doc-version-2)"
    echo "  title         PR title (optional, can be set in browser)"
    echo "  body          PR body (optional, can be set in browser)"
    echo
    echo "Environment variables:"
    echo "  GHE_URL       GitHub base URL (default: https://github.dev.example.com)"
    echo
    echo "Examples:"
    echo "  $0 PSA-MRVA/server-commander feature-branch main"
    echo "  $0 PSA-MRVA/server-commander feature-branch main 'My PR title'"
    echo "  $0 PSA-MRVA/server-commander feature-branch main 'Title' 'Description'"
    exit 1
fi

# ============================================================
# Configuration
# ============================================================

# GitHub URL (change for different GitHub instance)
# For github.com: https://github.com
# For GitHub Enterprise: https://github.dev.example.com
GHE_URL="${GHE_URL:-https://github.dev.example.com}"

# ============================================================
# URL encode function
# ============================================================

urlencode() {
    local string="${1}"
    local strlen=${#string}
    local encoded=""
    local pos c o

    for (( pos=0 ; pos<strlen ; pos++ )); do
        c=${string:$pos:1}
        case "$c" in
            [-_.~a-zA-Z0-9] ) o="${c}" ;;
            * ) printf -v o '%%%02x' "'$c"
        esac
        encoded+="${o}"
    done
    echo "${encoded}"
}

# ============================================================
# Construct PR URL
# ============================================================

# Basic URL structure:
# https://github.com/:owner/:repo/compare/:base...:head?quick_pull=1&title=...&body=...

# URL encode title and body if provided
ENCODED_TITLE=""
ENCODED_BODY=""

if [[ -n "$TITLE" ]]; then
    ENCODED_TITLE="&title=$(urlencode "$TITLE")"
fi

if [[ -n "$BODY" ]]; then
    ENCODED_BODY="&body=$(urlencode "$BODY")"
fi

# Construct full URL
PR_URL="${GHE_URL}/${REPO}/compare/${BASE_BRANCH}...${HEAD_BRANCH}?quick_pull=1${ENCODED_TITLE}${ENCODED_BODY}"

# ============================================================
# Display and open
# ============================================================

echo "Opening PR creation page..."
echo
echo "Repository: $REPO"
echo "From:       $HEAD_BRANCH"
echo "To:         $BASE_BRANCH"
if [[ -n "$TITLE" ]]; then
    echo "Title:      $TITLE"
fi
echo
echo "URL:"
echo "$PR_URL"
echo

# Open in browser
if command -v open &>/dev/null; then
    # macOS
    open "$PR_URL"
    echo "✓ Opened in default browser"
elif command -v xdg-open &>/dev/null; then
    # Linux
    xdg-open "$PR_URL"
    echo "✓ Opened in default browser"
elif command -v start &>/dev/null; then
    # Windows
    start "$PR_URL"
    echo "✓ Opened in default browser"
else
    echo "Could not detect browser opener."
    echo "Please copy the URL above and paste into your browser."
fi

echo
echo "If the browser doesn't open, copy the URL above."
