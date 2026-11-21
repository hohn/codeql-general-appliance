#!/bin/bash

# Usage: ./bump-mrvacommander-version.sh [branch-name]
# If branch-name is provided, it will be checked out in mrvacommander
# If omitted, the default branch (main) will be used

MRVA_BRANCH="${1:-main}"

echo '/!\   NOTE - this will need $ enterprise-gh bootstrap'
echo '             to have been run once, for the automatic'
echo '             PR functionality to work.'
echo
echo '      ALSO - since `go mod tidy` clones https://github.*'
echo '             URIs from go.mod files, you need your local git'
echo '             setup to support cloning those with your github'
echo '             username and password, e.g.'
echo 
echo '             export GHE_USER="your-username"'
echo '             export GHE_TOKEN="your-personal-access-token"'
echo '             git config --global credential.helper store'
echo '             touch ~/.git-credentials'
echo '             chmod 600 ~/.git-credentials'
echo '             printf ''https://%s:%s@github.dev.example.com\n'' "$GHE_USER" "$GHE_TOKEN" >> ~/.git-credentials'
echo
echo '----'
echo
echo 'This will attempt to do the following:'
echo ' - clone mrvacommander, agent-commander-argo, server-commander'
echo ' - create a new tag for the current mrvacommander'
echo ' - create PRs in agent-commander-argo and server-commander to update their mrvacommander dependency to that tag'
echo
echo 'Press return to continue'
read ret_to_cont

set -euo pipefail
set -x

export GOPRIVATE="*.dev.example.com"
export GOPROXY="https://goproxy.dev.example.com,direct"

cd "$(/bin/mktemp -d psa-mrva.XXXXXX)"
DDD_BASE=$PWD
/opt/example/bin/dpkg-distro-dev init .
/opt/example/bin/dpkg-distro-dev install go enterprise-gh figlet

export DDD_PATH=`/opt/example/bin/dpkg-distro-dev run bash -c 'echo $PATH'`
export DDD_LD_LIBRARY_PATH=`/opt/example/bin/dpkg-distro-dev run bash -c 'echo $LD_LIBRARY_PATH'`

git clone -b "$MRVA_BRANCH" github:PSA-MRVA/mrvacommander ./mrvacommander
git clone -b "$MRVA_BRANCH" github:PSA-MRVA/server-commander ./server-commander
git clone -b "$MRVA_BRANCH" github:PSA-MRVA/agent-commander-argo ./agent-commander-argo

cd mrvacommander

rm go.sum
PATH=$DDD_PATH LD_LIBRARY_PATH=$DDD_LD_LIBRARY_PATH go clean -modcache
PATH=$DDD_PATH LD_LIBRARY_PATH=$DDD_LD_LIBRARY_PATH go mod tidy

# Config
prefix="v"

# Find the latest vX.Y.Z tag reachable from the current branch (HEAD)
latest="$(
  git tag -l --merged HEAD --sort=-v:refname "${prefix}[0-9]*" \
  | grep -E "^${prefix}[0-9]+\.[0-9]+\.[0-9]+$" \
  | head -n1 || true
)"

if [[ -z "${latest:-}" ]]; then
  major=0; minor=0; patch=0
else
  ver="${latest#"$prefix"}"              # strip leading "v"
  IFS='.' read -r major minor patch <<<"$ver"
  patch="${patch:-0}"                    # default if somehow missing
fi

# Bump patch
((patch++)) || echo
NEW_VERSION="${prefix}${major}.${minor}.${patch}"

# Check if we're on main branch
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$CURRENT_BRANCH" != "main" ]]; then
  # For non-main branches, create a pre-release tag with branch name and timestamp
  SANITIZED_BRANCH="$(echo "$CURRENT_BRANCH" | sed 's/[^a-zA-Z0-9._-]/-/g')"
  TIMESTAMP="$(date +%Y%m%d%H%M%S)"
  NEW_VERSION="${prefix}${major}.${minor}.${patch}-${SANITIZED_BRANCH}.${TIMESTAMP}"
fi

echo "Latest tag: ${latest:-<none>}"
echo "Current branch: ${CURRENT_BRANCH}"
echo "Proposed tag:    ${NEW_VERSION}"

git status

# Create annotated tag
git tag -a "$NEW_VERSION" -m "Release $NEW_VERSION"
git push origin "$NEW_VERSION"

# Now reference the tag we just pushed, in each of agent-commander-argo and
# server-commander 

BRANCH_NAME="mrva_commander_bump_to_${NEW_VERSION}"

# Customize PR title and description based on branch
if [[ "$CURRENT_BRANCH" != "main" ]]; then
  PR_TITLE="[PRE-DEV TEST, DO NOT MERGE] bump mrvacommander dep to ${NEW_VERSION}"
  FIGLET_DO_NOT=$(PATH=$DDD_PATH LD_LIBRARY_PATH=$DDD_LD_LIBRARY_PATH figlet -d $DDD_BASE/refroot/amd64/opt/example/share/figlet "DO NOT")
  FIGLET_MERGE=$(PATH=$DDD_PATH LD_LIBRARY_PATH=$DDD_LD_LIBRARY_PATH figlet -d $DDD_BASE/refroot/amd64/opt/example/share/figlet "MERGE")
  DESCRIPTION="\`\`\`
${FIGLET_DO_NOT}
${FIGLET_MERGE}
\`\`\`

bump mrvacommander dep to ${NEW_VERSION}"
else
  PR_TITLE="bump mrvacommander dep to ${NEW_VERSION}"
  DESCRIPTION="bump mrvacommander dep to ${NEW_VERSION}"
fi

for TARGET_DIR in server-commander agent-commander-argo; do

    cd ..
    cd $TARGET_DIR

    git checkout -b $BRANCH_NAME
    rm go.sum

    sed -i -E "s|(github\.dev\.example\.com/PSA-MRVA/mrvacommander )v[0-9]+\.[0-9]+\.[0-9]+(-[^ ]*)?|\1${NEW_VERSION}|" go.mod

    PATH=$DDD_PATH LD_LIBRARY_PATH=$DDD_LD_LIBRARY_PATH go clean -modcache
    PATH=$DDD_PATH LD_LIBRARY_PATH=$DDD_LD_LIBRARY_PATH go mod tidy

    git status
    git commit -am "update dependency in go.mod"
    git push --set-upstream origin $BRANCH_NAME
    git status
    PATH=$DDD_PATH LD_LIBRARY_PATH=$DDD_LD_LIBRARY_PATH enterprise-gh create-pr --title "$PR_TITLE" --body "$DESCRIPTION" "PSA-MRVA/$TARGET_DIR:$BRANCH_NAME" "PSA-MRVA/$TARGET_DIR:main"
done

