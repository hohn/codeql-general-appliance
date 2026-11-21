#!/bin/bash

# Create a GitHub PR using curl and the GitHub API
# Works with both github.com and GitHub Enterprise
#
# Prerequisites:
#   - Personal access token with repo permissions
#   - Branch already pushed to remote
#
# Usage: ./create-pr-with-curl.sh <owner/repo> <head-branch> <base-branch> <title> [body]
#
# Examples:
#   ./create-pr-with-curl.sh PSA-MRVA/server-commander feature-branch main "Add feature"
#   ./create-pr-with-curl.sh PSA-MRVA/server-commander \
#       mrva_commander_bump_to_v0.6.0 \
#       mh-doc-version-2 \
#       "Bump mrvacommander to v0.6.0" \
#       "Updates dependency to latest version"

set -euo pipefail

# ============================================================
# Parse arguments
# ============================================================

REPO="${1:-}"
HEAD_BRANCH="${2:-}"
BASE_BRANCH="${3:-}"
TITLE="${4:-}"
BODY="${5:-}"

if [[ -z "$REPO" ]] || [[ -z "$HEAD_BRANCH" ]] || [[ -z "$BASE_BRANCH" ]] || [[ -z "$TITLE" ]]; then
    echo "Usage: $0 <owner/repo> <head-branch> <base-branch> <title> [body]"
    echo
    echo "Arguments:"
    echo "  owner/repo    Repository (e.g., PSA-MRVA/server-commander)"
    echo "  head-branch   Source branch (your feature branch)"
    echo "  base-branch   Target branch (e.g., main, mh-doc-version-2)"
    echo "  title         PR title"
    echo "  body          PR body/description (optional)"
    echo
    echo "Environment variables:"
    echo "  GHE_TOKEN     Personal access token (required)"
    echo "  GHE_API_URL   API base URL (default: https://api.github.dev.example.com)"
    echo
    echo "Example:"
    echo "  export GHE_TOKEN='your-token-here'"
    echo "  $0 PSA-MRVA/server-commander feature-branch main 'Add feature' 'Description here'"
    exit 1
fi

# ============================================================
# Configuration
# ============================================================

# GitHub Enterprise API URL (change for github.com)
# For github.com: https://api.github.com
# For GitHub Enterprise: https://api.github.dev.example.com
GHE_API_URL="${GHE_API_URL:-https://api.github.dev.example.com}"

# Personal access token
GHE_TOKEN="${GHE_TOKEN:-}"

if [[ -z "$GHE_TOKEN" ]]; then
    echo "Error: GHE_TOKEN environment variable not set"
    echo
    echo "Create a personal access token with 'repo' permissions:"
    echo "  1. Go to https://github.dev.example.com/settings/tokens"
    echo "  2. Generate new token with 'repo' scope"
    echo "  3. Export it: export GHE_TOKEN='your-token-here'"
    exit 1
fi

# ============================================================
# Construct API request
# ============================================================

# Build JSON payload
# Escape quotes in title and body
TITLE_ESCAPED=$(echo "$TITLE" | sed 's/"/\\"/g')
BODY_ESCAPED=$(echo "$BODY" | sed 's/"/\\"/g')

JSON_PAYLOAD=$(cat <<EOF
{
  "title": "$TITLE_ESCAPED",
  "body": "$BODY_ESCAPED",
  "head": "$HEAD_BRANCH",
  "base": "$BASE_BRANCH"
}
EOF
)

# API endpoint
API_ENDPOINT="${GHE_API_URL}/repos/${REPO}/pulls"

echo "Creating PR..."
echo "  Repository:  $REPO"
echo "  From:        $HEAD_BRANCH"
echo "  To:          $BASE_BRANCH"
echo "  Title:       $TITLE"
echo

# ============================================================
# Make API request
# ============================================================

RESPONSE=$(curl -s -w "\n%{http_code}" \
    -X POST \
    -H "Authorization: token ${GHE_TOKEN}" \
    -H "Accept: application/vnd.github.v3+json" \
    -H "Content-Type: application/json" \
    -d "$JSON_PAYLOAD" \
    "$API_ENDPOINT")

# Split response into body and status code
HTTP_BODY=$(echo "$RESPONSE" | head -n -1)
HTTP_CODE=$(echo "$RESPONSE" | tail -n 1)

# ============================================================
# Handle response
# ============================================================

if [[ "$HTTP_CODE" == "201" ]]; then
    echo "✓ PR created successfully!"
    echo

    # Extract PR URL from response
    PR_URL=$(echo "$HTTP_BODY" | grep -o '"html_url":"[^"]*"' | head -1 | sed 's/"html_url":"\(.*\)"/\1/')
    PR_NUMBER=$(echo "$HTTP_BODY" | grep -o '"number":[0-9]*' | head -1 | sed 's/"number"://')

    echo "PR #$PR_NUMBER: $PR_URL"

    # Try to open in browser (optional)
    if command -v open &>/dev/null; then
        read -r -p "Open PR in browser? [y/N] " response
        case "$response" in
            [yY][eE][sS]|[yY])
                open "$PR_URL"
                ;;
        esac
    fi

    exit 0
else
    echo "✗ Failed to create PR (HTTP $HTTP_CODE)"
    echo
    echo "Response:"
    echo "$HTTP_BODY" | python3 -m json.tool 2>/dev/null || echo "$HTTP_BODY"
    echo

    # Common error messages
    case "$HTTP_CODE" in
        401)
            echo "Authentication failed. Check your GHE_TOKEN."
            ;;
        404)
            echo "Repository or branch not found."
            echo "  - Verify repository: $REPO"
            echo "  - Verify branches exist: $HEAD_BRANCH, $BASE_BRANCH"
            ;;
        422)
            echo "Validation failed. Common causes:"
            echo "  - PR already exists for this branch"
            echo "  - Head branch doesn't exist or has no commits"
            echo "  - Base branch doesn't exist"
            echo "  - No commits between head and base"
            ;;
    esac

    exit 1
fi
