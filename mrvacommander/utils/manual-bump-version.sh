#!/bin/bash

# Manual version bump script for MRVA components
# Expands the automated bump-mrvacommander-version.sh into manual steps
#
# Prerequisites:
#   - On VPN
#   - On PSA main branch (or specified branch)
#   - Git credentials configured for github
#
# Usage: ./manual-bump-version.sh <version> [branch-name]
#   version:     The new version tag (e.g., v0.6.0)
#   branch-name: The branch to work on (default: main)

set -euo pipefail

NEW_VERSION="${1:-}"
MRVA_BRANCH="${2:-main}"

if [[ -z "$NEW_VERSION" ]]; then
    echo "Usage: $0 <version> [branch-name]"
    echo
    echo "Example:"
    echo "  $0 v0.6.0 main"
    echo "  $0 v0.6.1 mh-doc-version-2"
    exit 1
fi

# Validate version format
if [[ ! "$NEW_VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Error: Version must be in format vX.Y.Z (e.g., v0.6.0)"
    exit 1
fi

echo "=========================================="
echo "MRVA Manual Version Bump"
echo "=========================================="
echo "New version: $NEW_VERSION"
echo "Branch:      $MRVA_BRANCH"
echo "=========================================="
echo
echo "This script will:"
echo "  1. Tag and push mrvacommander"
echo "  2. Update and tag server-commander"
echo "  3. Update and tag agent-commander-argo"
echo
read -r -p "Press Enter to continue or Ctrl-C to abort..."
echo

# Configure Go proxy for internal packages
export GOPRIVATE="*.dev.example.com"
export GOPROXY="https://goproxy.dev.example.com,direct"

echo "✓ Go environment configured"
echo "  GOPRIVATE=$GOPRIVATE"
echo "  GOPROXY=$GOPROXY"
echo

# ============================================================
# Step 1: Tag and push mrvacommander
# ============================================================

echo "=========================================="
echo "Step 1: mrvacommander"
echo "=========================================="

cd ~/mrva/mrvacommander
echo "Working directory: $(pwd)"
echo

# Show current tags
echo "Current tags:"
git tag -l | cat
echo

# Clean and tidy
echo "Cleaning and tidying mrvacommander..."
go clean -modcache
rm -f go.sum
go mod tidy
echo "✓ go.mod tidied"
echo

# Show git status
echo "Git status:"
git status
echo

# Confirm before tagging
read -r -p "Tag mrvacommander as $NEW_VERSION? [y/N] " response
case "$response" in
    [yY][eE][sS]|[yY])
        # Create and push tag
        echo "Creating tag $NEW_VERSION..."
        git tag "$NEW_VERSION"
        echo "✓ Tag created"

        echo "Pushing to psa remote..."
        git push psa
        git push --tags psa
        echo "✓ mrvacommander tagged and pushed"
        ;;
    *)
        echo "Aborted. Skipping mrvacommander tag."
        exit 1
        ;;
esac

echo

# ============================================================
# Step 2: Update server-commander
# ============================================================

echo "=========================================="
echo "Step 2: server-commander"
echo "=========================================="

cd ~/c/example/psa-mrva/server-commander
echo "Working directory: $(pwd)"
echo

# Update go.mod with new version
echo "Updating go.mod with mrvacommander $NEW_VERSION..."
echo "Before:"
grep "github.dev.example.com/PSA-MRVA/mrvacommander" go.mod || echo "(not found)"

# Use sed to update the version
sed -i.bak -E "s|(github\.dev\.example\.com/PSA-MRVA/mrvacommander )v[0-9]+\.[0-9]+\.[0-9]+(-[^ ]*)?|\1${NEW_VERSION}|" go.mod
rm -f go.mod.bak

echo "After:"
grep "github.dev.example.com/PSA-MRVA/mrvacommander" go.mod
echo

# Clean and tidy
echo "Cleaning and tidying server-commander..."
go clean -modcache
rm -f go.sum
go mod tidy
echo "✓ go.mod tidied"
echo

# Build to verify
echo "Building server-commander..."
if go build .; then
    echo "✓ Build successful"
else
    echo "✗ Build failed"
    echo "Fix the errors above before continuing."
    exit 1
fi
echo

# Show current tags
echo "Current tags:"
git tag -l | cat
echo

# Git status
echo "Git status:"
git status
echo

# Commit, tag, and push
read -r -p "Commit, tag, and push server-commander as $NEW_VERSION? [y/N] " response
case "$response" in
    [yY][eE][sS]|[yY])
        git commit -am "update dependency tag in go.mod to $NEW_VERSION"
        git tag "$NEW_VERSION"
        git push --tags psa "$MRVA_BRANCH"
        echo "✓ server-commander committed, tagged, and pushed"
        ;;
    *)
        echo "Skipped server-commander commit/tag/push"
        ;;
esac

echo

# ============================================================
# Step 3: Update agent-commander-argo
# ============================================================

echo "=========================================="
echo "Step 3: agent-commander-argo"
echo "=========================================="

cd ~/c/example/psa-mrva/agent-commander-argo
echo "Working directory: $(pwd)"
echo

# Update go.mod with new version
echo "Updating go.mod with mrvacommander $NEW_VERSION..."
echo "Before:"
grep "github.dev.example.com/PSA-MRVA/mrvacommander" go.mod || echo "(not found)"

# Use sed to update the version
sed -i.bak -E "s|(github\.dev\.example\.com/PSA-MRVA/mrvacommander )v[0-9]+\.[0-9]+\.[0-9]+(-[^ ]*)?|\1${NEW_VERSION}|" go.mod
rm -f go.mod.bak

echo "After:"
grep "github.dev.example.com/PSA-MRVA/mrvacommander" go.mod
echo

# Clean and tidy
echo "Cleaning and tidying agent-commander-argo..."
go clean -modcache
rm -f go.sum
go mod tidy
echo "✓ go.mod tidied"
echo

# Build to verify
echo "Building agent-commander-argo..."
if go build .; then
    echo "✓ Build successful"
else
    echo "✗ Build failed"
    echo "Fix the errors above before continuing."
    exit 1
fi
echo

# Show current tags
echo "Current tags:"
git tag -l | cat
echo

# Git status
echo "Git status:"
git status
echo

# Commit, tag, and push
read -r -p "Commit, tag, and push agent-commander-argo as $NEW_VERSION? [y/N] " response
case "$response" in
    [yY][eE][sS]|[yY])
        git commit -am "update dependency tag in go.mod to $NEW_VERSION"
        git tag "$NEW_VERSION"
        git push --tags psa "$MRVA_BRANCH"
        echo "✓ agent-commander-argo committed, tagged, and pushed"
        ;;
    *)
        echo "Skipped agent-commander-argo commit/tag/push"
        ;;
esac

echo

# ============================================================
# Summary
# ============================================================

echo "=========================================="
echo "Summary"
echo "=========================================="
echo
echo "Version bump to $NEW_VERSION on branch $MRVA_BRANCH"
echo
echo "Components updated:"
echo "  ✓ mrvacommander        - tagged and pushed"
echo "  ✓ server-commander     - updated dependency, tagged, and pushed"
echo "  ✓ agent-commander-argo - updated dependency, tagged, and pushed"
echo
echo "Next steps:"
echo "  - Verify builds in CI/CD"
echo "  - Test deployments"
echo "  - Update documentation if needed"
echo
echo "Done!"
