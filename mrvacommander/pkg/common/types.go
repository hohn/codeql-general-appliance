package common

// NameWithOwner represents a repository name and its owner name.
type NameWithOwner struct {
	Owner string
	Repo  string
}

// Status represents the status of a job.
type Status int

const (
	// External statuses — visible to the VS Code client via the API.
	// Per-repo: "pending", "in_progress", "succeeded", "failed", "canceled", "timed_out"
	// Overall:  "in_progress", "succeeded", "failed", "cancelled"
	StatusPending    Status = iota // Per-repo: "pending"
	StatusInProgress               // Per-repo: "in_progress", Overall: "in_progress"
	StatusSucceeded                // Per-repo: "succeeded",   Overall: "succeeded"
	StatusFailed                   // Per-repo: "failed",      Overall: "failed"
	StatusCanceled                 // Per-repo: "canceled",    Overall: "cancelled"
	StatusTimedOut                 // Per-repo: "timed_out"

	// Internal statuses — used by server & agent only, never sent to VS Code.
	StatusQueued // Job selected by fair scheduling, available for worker claiming
)

// WorkerStatus represents the status of a worker in the pool.
type WorkerStatus int

const (
	WorkerIdle     WorkerStatus = iota // Registered, polling for jobs
	WorkerBusy                         // Executing a claimed job
	WorkerDraining                     // Pool manager requested shutdown; finish current job then exit
	WorkerExited                       // Worker has terminated
)

// ToRepoStatusString returns the per-repo analysis_status string for the VS Code API.
// VS Code expects: "pending", "in_progress", "succeeded", "failed", "canceled", "timed_out".
// Internal statuses are mapped to their nearest VS Code equivalent.
func (s Status) ToRepoStatusString() string {
	switch s {
	case StatusPending:
		return "pending"
	case StatusInProgress:
		return "in_progress"
	case StatusSucceeded:
		return "succeeded"
	case StatusFailed:
		return "failed"
	case StatusCanceled:
		return "canceled"
	case StatusTimedOut:
		return "timed_out"
	case StatusQueued:
		return "pending"
	default:
		return "pending"
	}
}

// ToOverallStatusString returns the overall variant analysis status string for the VS Code API.
// VS Code expects: "in_progress", "succeeded", "failed", "cancelled" (double-l).
// Internal statuses are mapped to their nearest VS Code equivalent.
func (s Status) ToOverallStatusString() string {
	switch s {
	case StatusSucceeded:
		return "succeeded"
	case StatusFailed:
		return "failed"
	case StatusCanceled:
		return "cancelled" // VS Code uses British spelling for overall status
	default:
		return "in_progress"
	}
}

// ToExternalString returns a wire-format status string.
// Deprecated: use ToRepoStatusString or ToOverallStatusString instead.
func (s Status) ToExternalString() string {
	return s.ToRepoStatusString()
}

type JobSpec struct {
	SessionID int
	NameWithOwner
}

type StatusSummary struct {
	Overall Status
	Counts  map[Status]int
}
