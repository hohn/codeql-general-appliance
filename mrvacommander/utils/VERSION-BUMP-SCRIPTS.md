# Version Bump Scripts

This directory contains several scripts for bumping MRVA component versions. Choose the one that fits your workflow.

## Quick Reference

| Script                          | Use Case                       | Interaction Level             |
|---------------------------------|--------------------------------|-------------------------------|
| `bump-mrvacommander-version.sh` | Automated PR creation          | Minimal (one confirmation)    |
| `bump-version-interactive.sh`   | Manual workflow with prompts   | High (confirms each step)     |
| `manual-bump-version.sh`        | Semi-automated manual workflow | Medium (confirms major steps) |
| `manual-bump-reference.sh`      | Copy-paste reference           | None (reference only)         |

## Scripts

### 1. `bump-mrvacommander-version.sh` (Original Automated)

**Use when:** You want to create PRs automatically via `enterprise-gh`

**Prerequisites:**
- `enterprise-gh bootstrap` has been run
- Git credentials configured
- Access to dpkg-distro-dev

**Usage:**
```bash
./bump-mrvacommander-version.sh [branch-name]
# Example:
./bump-mrvacommander-version.sh main
./bump-mrvacommander-version.sh mh-doc-version-2
```

**What it does:**
1. Creates temporary workspace with dpkg-distro-dev
2. Clones repos (mrvacommander, server-commander, agent-commander-argo)
3. Determines next version number automatically
4. Tags mrvacommander
5. Updates dependencies in server-commander and agent-commander-argo
6. Creates PRs via `enterprise-gh create-pr`

**Note:** Currently has a 404 error with PR creation that needs fixing.

---

### 2. `bump-version-interactive.sh` (NEW - Interactive Manual)

**Use when:** You want manual control with helpful prompts at each step

**Prerequisites:**
- On VPN
- Git credentials configured
- Working directories exist

**Usage:**
```bash
./bump-version-interactive.sh v0.6.0 main
./bump-version-interactive.sh v0.6.1 mh-doc-version-2
```

**What it does:**
1. Prompts before each major operation
2. Shows what will be done before doing it
3. Validates builds before tagging
4. Color-coded output (✓ ✗ ⚠ ℹ)
5. Allows skipping steps

**Example session:**
```
? Ready to proceed? [y/N] y
ℹ Setting up Go environment...
✓ Environment configured

? Clean and tidy mrvacommander? [y/N] y
✓ Cleaned and tidied

? Create tag v0.6.0 in mrvacommander? [y/N] y
✓ Tag v0.6.0 created

...
```

---

### 3. `manual-bump-version.sh` (NEW - Semi-Automated Manual)

**Use when:** You want a script that follows manual workflow but automates the tedious parts

**Prerequisites:**
- On VPN
- Git credentials configured
- Working directories exist

**Usage:**
```bash
./manual-bump-version.sh v0.6.0 main
./manual-bump-version.sh v0.6.1 mh-doc-version-2
```

**What it does:**
1. Validates version format
2. Shows before/after for go.mod changes
3. Builds to verify before committing
4. Confirms before tagging/pushing
5. Processes all three components in sequence

**Confirmation points:**
- Tag mrvacommander? [y/N]
- Commit/tag/push server-commander? [y/N]
- Commit/tag/push agent-commander-argo? [y/N]

---

### 4. `manual-bump-reference.sh` (NEW - Reference/Checklist)

**Use when:** You want to copy-paste individual commands

**This is NOT meant to be run directly.** It's a reference showing:
- Individual commands for each step
- Comments explaining what each command does
- Alternative approaches (sed vs manual editing)
- A checklist at the end

**Usage:**
```bash
# Don't run it:
# ./manual-bump-reference.sh

# Instead, open it in an editor and copy sections:
cat manual-bump-reference.sh
# Copy the commands you need
```

---

## Workflow Comparison

### Automated Workflow (bump-mrvacommander-version.sh)

```
User runs script
  ↓
Script creates temp workspace
  ↓
Clones all repos
  ↓
Auto-calculates version
  ↓
Tags mrvacommander
  ↓
For each dependent repo:
  - Updates go.mod
  - Creates PR via enterprise-gh
```

**Pros:** Fast, repeatable, creates PRs automatically
**Cons:** Less control, requires enterprise-gh, has 404 error currently

---

### Interactive Manual Workflow (bump-version-interactive.sh)

```
User runs script with version
  ↓
For each component:
  Shows current state
    ↓
  Prompts: "Do this step?"
    ↓
  If yes: Does step and shows result
    ↓
  Prompts: "Continue?"
```

**Pros:** Full visibility, can skip steps, validates before committing
**Cons:** Slower, requires many confirmations

---

### Semi-Automated Manual Workflow (manual-bump-version.sh)

```
User runs script with version
  ↓
Script validates input
  ↓
For each component:
  Automates tedious parts
    ↓
  Shows important info
    ↓
  Confirms at decision points
```

**Pros:** Good balance of automation and control
**Cons:** Less flexibility than interactive

---

## Common Workflow

Regardless of which script you use, the flow is:

1. **mrvacommander** (library)
   - Clean and tidy
   - Tag with new version
   - Push tag

2. **server-commander** (depends on mrvacommander)
   - Update go.mod dependency to new mrvacommander tag
   - Clean, tidy, build
   - Tag with new version
   - Push

3. **agent-commander-argo** (depends on mrvacommander)
   - Update go.mod dependency to new mrvacommander tag
   - Clean, tidy, build
   - Tag with new version
   - Push

## Environment Variables

All scripts use these Go environment variables:

```bash
export GOPRIVATE="*.dev.example.com"
export GOPROXY="https://goproxy.dev.example.com,direct"
```

These are required for accessing internal packages.

## Version Format

All scripts expect semantic versioning:

- ✅ `v0.6.0`
- ✅ `v1.0.0`
- ✅ `v2.3.4`
- ❌ `0.6.0` (missing 'v' prefix)
- ❌ `v1.0` (incomplete)

For development branches, the automated script appends branch name and timestamp:
- `v0.6.0-mh-doc-version-2.20260402123456`

## Directories

The scripts expect these directory structures:

```
~/mrva/mrvacommander/              # mrvacommander repo
~/c/example/psa-mrva/
├── server-commander/              # server-commander repo
├── agent-commander-argo/          # agent-commander-argo repo
└── mrvacommander/                 # script location
    ├── bump-mrvacommander-version.sh
    ├── bump-version-interactive.sh
    ├── manual-bump-version.sh
    └── manual-bump-reference.sh
```

## Troubleshooting

### "Directory not found"
- Check directory paths in the script
- Ensure repos are cloned in expected locations

### "go mod tidy failed"
- Check `GOPRIVATE` and `GOPROXY` environment variables
- Verify VPN connection
- Run `go clean -modcache` and retry

### "Build failed"
- Check error messages from `go build`
- Ensure dependency versions are compatible
- Check for merge conflicts in go.mod

### "Push failed"
- Verify git credentials
- Check remote name (should be 'psa')
- Verify branch name

### "Tag already exists"
- List tags: `git tag -l | grep v0.6.0`
- Delete local tag: `git tag -d v0.6.0`
- Delete remote tag: `git push --delete psa v0.6.0`

## Which Script Should I Use?

### Use `bump-mrvacommander-version.sh` if:
- ✅ You want PRs created automatically
- ✅ You trust the auto-version calculation
- ✅ You have enterprise-gh working
- ⚠️ Currently has 404 error

### Use `bump-version-interactive.sh` if:
- ✅ You want to see every step
- ✅ You want to verify before each action
- ✅ You're learning the process
- ✅ You want to skip certain steps

### Use `manual-bump-version.sh` if:
- ✅ You want automation but with checkpoints
- ✅ You want to specify the version explicitly
- ✅ You want to review changes before committing

### Use `manual-bump-reference.sh` if:
- ✅ You want to run commands manually
- ✅ You need a reference for what to do
- ✅ You're customizing the workflow

## Examples

### Bump to v0.6.0 on main branch

**Interactive (recommended for first time):**
```bash
./bump-version-interactive.sh v0.6.0 main
```

**Semi-automated:**
```bash
./manual-bump-version.sh v0.6.0 main
```

**Fully automated (when 404 is fixed):**
```bash
./bump-mrvacommander-version.sh main
```

### Bump to v0.6.1 on development branch

**Interactive:**
```bash
./bump-version-interactive.sh v0.6.1 mh-doc-version-2
```

**Semi-automated:**
```bash
./manual-bump-version.sh v0.6.1 mh-doc-version-2
```

## Future Improvements

- [ ] Fix 404 error in `bump-mrvacommander-version.sh`
- [ ] Add dry-run mode to all scripts
- [ ] Add rollback functionality
- [ ] Validate that version doesn't already exist
- [ ] Check CI/CD status before tagging
- [ ] Add support for major/minor version bumps
