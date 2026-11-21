#!/bin/bash

# Interactive version bump script for MRVA components
# Prompts at each step and shows exactly what will be done
#
# Prerequisites:
#   - On VPN
#   - Git credentials configured for github
#   - Working in the correct branch
#
# Usage: ./bump-version-interactive.sh <version> [branch-name]

set -euo pipefail

NEW_VERSION="${1:-}"
MRVA_BRANCH="${2:-main}"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

info() {
    echo -e "${BLUE}ℹ${NC} $*"
}

success() {
    echo -e "${GREEN}✓${NC} $*"
}

warn() {
    echo -e "${YELLOW}⚠${NC} $*"
}

error() {
    echo -e "${RED}✗${NC} $*"
}

prompt() {
    echo -e "${YELLOW}?${NC} $*"
}

# ============================================================
# Validation
# ============================================================

if [[ -z "$NEW_VERSION" ]]; then
    error "Version required"
    echo
    echo "Usage: $0 <version> [branch-name]"
    echo
    echo "Examples:"
    echo "  $0 v0.6.0 main"
    echo "  $0 v0.6.1 mh-doc-version-2"
    exit 1
fi

if [[ ! "$NEW_VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    error "Version must be in format vX.Y.Z (e.g., v0.6.0)"
    exit 1
fi

# ============================================================
# Header
# ============================================================

echo
echo "═══════════════════════════════════════════"
echo "  MRVA Interactive Version Bump"
echo "═══════════════════════════════════════════"
echo
info "New version: ${NEW_VERSION}"
info "Branch:      ${MRVA_BRANCH}"
echo
echo "This will update:"
echo "  1. mrvacommander"
echo "  2. server-commander"
echo "  3. agent-commander-argo"
echo
prompt "Ready to proceed? [y/N]"
read -r response
case "$response" in
    [yY][eE][sS]|[yY]) ;;
    *) error "Aborted."; exit 0 ;;
esac

# ============================================================
# Environment
# ============================================================

echo
info "Setting up Go environment..."
export GOPRIVATE="*.dev.example.com"
export GOPROXY="https://goproxy.dev.example.com,direct"
success "Environment configured"
echo "  GOPRIVATE=${GOPRIVATE}"
echo "  GOPROXY=${GOPROXY}"

# ============================================================
# Function: Clean and tidy Go module
# ============================================================

clean_and_tidy() {
    local component="$1"
    info "Cleaning ${component}..."
    go clean -modcache || { error "go clean failed"; return 1; }
    rm -f go.sum || { error "rm go.sum failed"; return 1; }
    go mod tidy || { error "go mod tidy failed"; return 1; }
    success "Cleaned and tidied"
}

# ============================================================
# Function: Show current tags
# ============================================================

show_tags() {
    local component="$1"
    echo
    info "Current tags in ${component}:"
    git tag -l | cat | tail -10 || echo "  (no tags)"
}

# ============================================================
# STEP 1: mrvacommander
# ============================================================

echo
echo "═══════════════════════════════════════════"
echo "  Step 1/3: mrvacommander"
echo "═══════════════════════════════════════════"


if [[ ! -d ~/c/example/psa-mrva/mrvacommander ]]; then
    error "Directory not found: ~/c/example/psa-mrva/mrvacommander"
    exit 1
fi

cd ~/c/example/psa-mrva/mrvacommander
info "Working in: $(pwd)"

show_tags "mrvacommander"

echo
prompt "Clean and tidy mrvacommander? [y/N]"
read -r response
case "$response" in
    [yY][eE][sS]|[yY])
        clean_and_tidy "mrvacommander" || exit 1
        ;;
    *)
        warn "Skipped clean and tidy"
        ;;
esac

echo
info "Current git status:"
git status --short || git status

echo
prompt "Create tag ${NEW_VERSION} in mrvacommander? [y/N]"
read -r response
case "$response" in
    [yY][eE][sS]|[yY])
        git tag "${NEW_VERSION}" || { error "Failed to create tag"; exit 1; }
        success "Tag ${NEW_VERSION} created"
        ;;
    *)
        error "Tag creation required to continue"
        exit 1
        ;;
esac

echo
prompt "Push mrvacommander to psa remote (branch + tags)? [y/N]"
read -r response
case "$response" in
    [yY][eE][sS]|[yY])
        git push origin || { error "Push failed"; exit 1; }
        git push --tags origin || { error "Push tags failed"; exit 1; }
        success "Pushed to origin remote"
        ;;
    *)
        warn "Skipped push - you'll need to push manually later"
        ;;
esac

# ============================================================
# STEP 2: server-commander
# ============================================================

echo
echo "═══════════════════════════════════════════"
echo "  Step 2/3: server-commander"
echo "═══════════════════════════════════════════"

if [[ ! -d ~/c/example/psa-mrva/server-commander ]]; then
    error "Directory not found: ~/c/example/psa-mrva/server-commander"
    exit 1
fi

cd ~/c/example/psa-mrva/server-commander
info "Working in: $(pwd)"

show_tags "server-commander"

echo
info "Current mrvacommander dependency:"
grep "github.dev.example.com/PSA-MRVA/mrvacommander" go.mod || warn "Not found in go.mod"

echo
prompt "Update go.mod to use mrvacommander ${NEW_VERSION}? [y/N]"
read -r response
case "$response" in
    [yY][eE][sS]|[yY])
        sed -i.bak -E "s|(github\.dev\.example\.com/PSA-MRVA/mrvacommander )v[0-9]+\.[0-9]+\.[0-9]+(-[^ ]*)?|\1${NEW_VERSION}|" go.mod
        rm -f go.mod.bak
        success "Updated go.mod"
        info "New dependency:"
        grep "github.dev.example.com/PSA-MRVA/mrvacommander" go.mod
        ;;
    *)
        warn "You'll need to edit go.mod manually"
        ;;
esac

echo
prompt "Clean and tidy server-commander? [y/N]"
read -r response
case "$response" in
    [yY][eE][sS]|[yY])
        clean_and_tidy "server-commander" || exit 1
        ;;
    *)
        warn "Skipped clean and tidy"
        ;;
esac

echo
info "Building server-commander to verify..."
if go build .; then
    success "Build successful"
else
    error "Build failed - fix errors before continuing"
    exit 1
fi

echo
info "Git status:"
git status --short || git status

echo
prompt "Commit changes in server-commander? [y/N]"
read -r response
case "$response" in
    [yY][eE][sS]|[yY])
        git commit -am "update dependency tag in go.mod to ${NEW_VERSION}" || {
            error "Commit failed"
            exit 1
        }
        success "Changes committed"
        ;;
    *)
        warn "Changes not committed"
        ;;
esac

echo
prompt "Tag server-commander as ${NEW_VERSION}? [y/N]"
read -r response
case "$response" in
    [yY][eE][sS]|[yY])
        git tag "${NEW_VERSION}" || { error "Tag failed"; exit 1; }
        success "Tagged as ${NEW_VERSION}"
        ;;
    *)
        warn "Not tagged"
        ;;
esac

echo
prompt "Push server-commander to origin remote? [y/N]"
read -r response
case "$response" in
    [yY][eE][sS]|[yY])
        git push --tags origin "${MRVA_BRANCH}" || { error "Push failed"; exit 1; }
        success "Pushed to origin/${MRVA_BRANCH}"
        ;;
    *)
        warn "Not pushed"
        ;;
esac

# ============================================================
# STEP 3: agent-commander-argo
# ============================================================

echo
echo "═══════════════════════════════════════════"
echo "  Step 3/3: agent-commander-argo"
echo "═══════════════════════════════════════════"

if [[ ! -d ~/c/example/psa-mrva/agent-commander-argo ]]; then
    error "Directory not found: ~/c/example/psa-mrva/agent-commander-argo"
    exit 1
fi

cd ~/c/example/psa-mrva/agent-commander-argo
info "Working in: $(pwd)"

show_tags "agent-commander-argo"

echo
info "Current mrvacommander dependency:"
grep "github.dev.example.com/PSA-MRVA/mrvacommander" go.mod || warn "Not found in go.mod"

echo
prompt "Update go.mod to use mrvacommander ${NEW_VERSION}? [y/N]"
read -r response
case "$response" in
    [yY][eE][sS]|[yY])
        sed -i.bak -E "s|(github\.dev\.example\.com/PSA-MRVA/mrvacommander )v[0-9]+\.[0-9]+\.[0-9]+(-[^ ]*)?|\1${NEW_VERSION}|" go.mod
        rm -f go.mod.bak
        success "Updated go.mod"
        info "New dependency:"
        grep "github.dev.example.com/PSA-MRVA/mrvacommander" go.mod
        ;;
    *)
        warn "You'll need to edit go.mod manually"
        ;;
esac

echo
prompt "Clean and tidy agent-commander-argo? [y/N]"
read -r response
case "$response" in
    [yY][eE][sS]|[yY])
        clean_and_tidy "agent-commander-argo" || exit 1
        ;;
    *)
        warn "Skipped clean and tidy"
        ;;
esac

echo
info "Building agent-commander-argo to verify..."
if go build .; then
    success "Build successful"
else
    error "Build failed - fix errors before continuing"
    exit 1
fi

echo
info "Git status:"
git status --short || git status

echo
prompt "Commit changes in agent-commander-argo? [y/N]"
read -r response
case "$response" in
    [yY][eE][sS]|[yY])
        git commit -am "update dependency tag in go.mod to ${NEW_VERSION}" || {
            error "Commit failed"
            exit 1
        }
        success "Changes committed"
        ;;
    *)
        warn "Changes not committed"
        ;;
esac

echo
prompt "Tag agent-commander-argo as ${NEW_VERSION}? [y/N]"
read -r response
case "$response" in
    [yY][eE][sS]|[yY])
        git tag "${NEW_VERSION}" || { error "Tag failed"; exit 1; }
        success "Tagged as ${NEW_VERSION}"
        ;;
    *)
        warn "Not tagged"
        ;;
esac

echo
prompt "Push agent-commander-argo to origin remote? [y/N]"
read -r response
case "$response" in
    [yY][eE][sS]|[yY])
        git push --tags origin "${MRVA_BRANCH}" || { error "Push failed"; exit 1; }
        success "Pushed to origin/${MRVA_BRANCH}"
        ;;
    *)
        warn "Not pushed"
        ;;
esac

# ============================================================
# Summary
# ============================================================

echo
echo "═══════════════════════════════════════════"
echo "  Summary"
echo "═══════════════════════════════════════════"
echo
success "Version bump to ${NEW_VERSION} complete!"
echo
info "Updated components:"
echo "  ✓ mrvacommander"
echo "  ✓ server-commander"
echo "  ✓ agent-commander-argo"
echo
info "Branch: ${MRVA_BRANCH}"
echo
info "Next steps:"
echo "  - Verify builds in CI/CD"
echo "  - Test deployments"
echo "  - Create PRs if needed"
echo
