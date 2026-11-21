#!/bin/bash

# Manual version bump - Reference script showing step-by-step expansion
# This script shows the manual steps from bump-mrvacommander-version.sh
# expanded into individual commands for the mh-doc-version-2 branch
#
# This is a REFERENCE - copy and paste sections as needed
# Do NOT run this script directly - it's meant to be executed section by section
#

# Replace v0.7.12 with your desired version


# ============================================================
# PREREQUISITES
# ============================================================

# On VPN
# On PSA main branch (or your working branch)
# Git credentials configured

# ============================================================
# ENVIRONMENT SETUP
# ============================================================

# Export Go proxy settings for internal packages
export GOPRIVATE="*.dev.example.com"
export GOPROXY="https://goproxy.dev.example.com,direct"

# ============================================================
# STEP 1: mrvacommander - Clean, Tag, and Push
# ============================================================
cd ~/c/example/psa-mrva/mrvacommander

# verify current branch
git status |grep 'On branch'

# Show current tags
git tag -l | cat

# Clean Go cache and dependencies (fixes unresolved imports)
go clean -modcache
rm go.sum
go mod tidy

# Create and push new tag
git status                      # nothing to commit?

git commit -am "dependency update" 
git tag v0.7.12
git push origin
git push --tags origin mh-doc-version-2

# ============================================================
# STEP 2: server-commander - Update Dependency and Tag
# ============================================================
cd ~/c/example/psa-mrva/server-commander

# verify current branch
git status |grep 'On branch'

# Fetch latest changes (optional)
# git fetch

# Edit go.mod to update mrvacommander version tag
# Change the version manually in go.mod, or use sed:
sed -i '' -E "s|(github\.dev\.example\.com/PSA-MRVA/mrvacommander )v[0-9]+\.[0-9]+\.[0-9]+(-[^ ]*)?|\1v0.7.12|" go.mod
# check
tail -2 go.mod

# Show current tags
git tag -l | cat

# Clean and build
go clean -modcache
rm go.sum
# can reset the tag in go.mod if mrvacommander has not been pushed
go mod tidy                     
# check
tail -2 go.mod

# Verify build works
go build .

# Commit, tag, and push
# Replace v0.7.12 with your desired version
git status                      # nothing to commit?

git commit -am "update dependency tag in go.mod" 
git tag v0.7.12 
git push --tags origin mh-doc-version-2

# ============================================================
# STEP 3: agent-commander-argo - Update Dependency and Tag
# ============================================================
cd ~/c/example/psa-mrva/agent-commander-argo

# Fetch latest changes (optional)
# git fetch

# Edit go.mod to update mrvacommander version tag
# Change the version manually -- go.mod --  or use sed:
sed -i '' -E "s|(github\.dev\.example\.com/PSA-MRVA/mrvacommander )v[0-9]+\.[0-9]+\.[0-9]+(-[^ ]*)?|\1v0.7.12|" go.mod
# check
tail -2 go.mod

# Show current tags
git tag -l | cat

# Clean and build
go clean -modcache
rm go.sum
go mod tidy
# check tag
tail -2 go.mod

# Verify build works
go build .

# Commit, tag, and push
# Replace v0.7.12 with your desired version
git status                      # nothing to commit?

git commit -am "update dependency tag in go.mod" 
git tag v0.7.12 
git push --tags origin mh-doc-version-2

# Next, create PR on github; base is main, branch mh-doc-version-2
# - https://github.dev.example.com/PSA-MRVA/server-commander/pulls
# - https://github.dev.example.com/PSA-MRVA/agent-commander-argo/pulls


# ============================================================
# ALTERNATIVE: For non-main branches (like mh-doc-version-2)
# ============================================================

# When working on a feature branch, replace the push commands with:
# git push --tags origin <branch-name>

# Example for mh-doc-version-2 branch:
# git commit -am "update dependency tag in go.mod" && \
#     git tag v0.7.12 && \
#     git push --tags origin mh-doc-version-2

# ============================================================
# NOTES
# ============================================================

# 1. The go.mod edit can be done manually with your editor
#    or using sed as shown in the comments

# 2. Always verify the build succeeds before tagging/pushing

# 3. For development branches, you may want to use a different
#    tagging scheme (e.g., v0.7.12-mh-doc-version-2.20260402123456)

# 4. The automated script creates PRs, but manual workflow
#    pushes directly to the branch

# 5. Components to update (in order):
#    - mrvacommander       (tag only, no dependency updates)
#    - server-commander    (depends on mrvacommander)
#    - agent-commander-argo (depends on mrvacommander)

# ============================================================
# CHECKLIST
# ============================================================

# [ ] Set GOPRIVATE and GOPROXY environment variables
# [ ] mrvacommander:
#     [ ] cd to directory
#     [ ] git tag -l | cat (check current tags)
#     [ ] go clean -modcache && rm go.sum && go mod tidy
#     [ ] git tag vX.Y.Z
#     [ ] git push origin && git push --tags origin
# [ ] server-commander:
#     [ ] cd to directory
#     [ ] Update go.mod with new mrvacommander version
#     [ ] go clean -modcache && rm go.sum && go mod tidy
#     [ ] go build . (verify)
#     [ ] git commit -am "update dependency tag in go.mod"
#     [ ] git tag vX.Y.Z
#     [ ] git push --tags origin <branch>
# [ ] agent-commander-argo:
#     [ ] cd to directory
#     [ ] Update go.mod with new mrvacommander version
#     [ ] go clean -modcache && rm go.sum && go mod tidy
#     [ ] go build . (verify)
#     [ ] git commit -am "update dependency tag in go.mod"
#     [ ] git tag vX.Y.Z
#     [ ] git push --tags origin <branch>
