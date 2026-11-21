package server

import (
	"bytes"
	"crypto/sha1"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/hohn/mrvacommander/pkg/artifactstore"
	"github.com/hohn/mrvacommander/pkg/common"
	"github.com/hohn/mrvacommander/pkg/queue"
	"github.com/hohn/mrvacommander/pkg/state"
	"github.com/hohn/mrvacommander/utils"

	"github.com/gorilla/mux"
)

func (c *CommanderSingle) startAnalyses(
	analysisRepos []common.NameWithOwner,
	queryPackLocation artifactstore.ArtifactLocation,
	sessionId int,
	queryLanguage queue.QueryLanguage,
	user string) {

	slog.Info("Preparing analysis jobs for scheduling", "count", len(analysisRepos), "user", user)

	for _, nwo := range analysisRepos {
		jobSpec := common.JobSpec{
			SessionID:     sessionId,
			NameWithOwner: nwo,
		}
		info := queue.AnalyzeJob{
			Spec:              jobSpec,
			QueryPackLocation: queryPackLocation,
			QueryLanguage:     queryLanguage,
		}

		// Set initial status to pending
		c.v.State.SetStatus(jobSpec, common.StatusPending)

		// Add job to the job list
		c.v.State.AddJob(info)

		// Note: Jobs are not dispatched through a message broker. The
		// scheduler picks them up from Postgres and schedules them to
		// Argo Workflows based on fair scheduling policies.
	}

	// Wake the pool manager now so newly-submitted jobs are queued and
	// workers spawned immediately, instead of waiting up to a full
	// ScaleCheckInterval for the next periodic cycle.
	//
	// TODO(kludge): this is a pragmatic latency fix, not the real design.
	// It was added to avoid the painful up-to-ScaleCheckInterval first-spawn
	// delay; production originally relied on the periodic cycle to sidestep
	// other problems. Revisit: submission and scheduling should be coupled
	// through a proper mechanism rather than a fire-and-forget wake.
	c.v.PoolManager.TriggerScheduling()
}

func setupEndpoints(c CommanderAPI, auth Authenticator, sv *sysView) {
	// Secure default: if no authenticator was wired, fall back to the
	// production JWT validator rather than an open endpoint.
	if auth == nil {
		auth = NewJWTAuthenticator()
	}

	r := mux.NewRouter()

	// Root handler
	r.HandleFunc("/", c.RootHandler)

	// Endpoints for submitting new analyses (require authentication)
	authRouter := r.PathPrefix("").Subrouter()
	authRouter.Use(AuthMiddleware(auth))
	authRouter.HandleFunc("/repos/{owner}/{repo}/code-scanning/codeql/variant-analyses", c.MRVARequest)
	authRouter.HandleFunc("/repositories/{controller_repo_id}/code-scanning/codeql/variant-analyses", c.MRVARequestID)

	// Cancel endpoint (requires authentication)
	authRouter.HandleFunc("/repositories/{repo_id}/code-scanning/codeql/variant-analyses/{run_id}/cancel", c.CancelVariantAnalysis).Methods("POST")

	// System-state dashboard. In standalone it is open (RequireAuth=false); in
	// production it is registered behind the same auth middleware as submissions.
	if sv != nil {
		if sv.cfg.RequireAuth {
			authRouter.HandleFunc("/sysview", sv.handlePage)
			authRouter.HandleFunc("/sysview/data", sv.handleData)
		} else {
			r.HandleFunc("/sysview", sv.handlePage)
			r.HandleFunc("/sysview/data", sv.handleData)
		}
	}

	// Endpoints for status requests
	// This is also the first request made when downloading; the difference is in the client-side handling.
	// TODO: better document / standardize this: {codeql_variant_analysis_id} is the session ID
	r.HandleFunc("/repos/{owner}/{repo}/code-scanning/codeql/variant-analyses/{codeql_variant_analysis_id}", c.MRVAStatus)
	r.HandleFunc("/repositories/{controller_repo_id}/code-scanning/codeql/variant-analyses/{codeql_variant_analysis_id}", c.MRVAStatusID)

	// XX: Handle endpoint
	//			  /repos/tdlib/telegram-bot-apictsj8529d9/code-scanning/codeql/databases/cpp
	// Endpoints for getting a URL to download artifacts
	//			  /repos/tdlib	     /telegram.../code-scanning/codeql/databases/cpp
	r.HandleFunc("/repos/{repo_owner}/{repo_name}/code-scanning/codeql/databases/{repo_language}", c.MRVADownloadQLDB)
	r.HandleFunc("/repos/{controller_owner}/{controller_repo}/code-scanning/codeql/variant-analyses/{codeql_variant_analysis_id}/repos/{repo_owner}/{repo_name}", c.MRVADownloadArtifact)
	r.HandleFunc("/repositories/{controller_repo_id}/code-scanning/codeql/variant-analyses/{codeql_variant_analysis_id}/repositories/{repository_id}", c.MRVADownloadArtifactID)

	// Endpoint to serve downloads using encoded JobSpec
	r.HandleFunc("/download/{encoded_job_spec}", c.MRVADownloadServe)

	// Browsers request this automatically when opening sysview.
	r.HandleFunc("/favicon.ico", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusNoContent)
	}).Methods("GET")

	// Handler for unhandled endpoints
	r.NotFoundHandler = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		slog.Error("Unhandled endpoint", "method", r.Method, "uri", r.RequestURI)
		http.Error(w, "Not Found", http.StatusNotFound)
	})

	go ListenAndServe(r)
}

func ListenAndServe(r *mux.Router) {
	// Bind to a port and pass our router in
	// The port is configurable via environment variable or default to 8080
	port := os.Getenv("SERVER_PORT")
	if port == "" {
		port = "8080"
	}

	err := http.ListenAndServe(":"+port, r)
	if err != nil {
		slog.Error("Error starting server:", "error", err)
		os.Exit(1)
	}
}

// TODO: check the caller as well so that it still returns statuses if no jobs exist (e.g. missing dbs) --
func (c *CommanderSingle) submitEmptyStatusResponse(w http.ResponseWriter,
	jsSessionID int,
) {
	slog.Debug("Submitting status response for empty job list", "job_id", jsSessionID)

	// TODO Can/need this struct contain more info when |jobs| == 0?
	ji := common.JobInfo{
		QueryLanguage: "",
		CreatedAt:     "",
		UpdatedAt:     "",

		SkippedRepositories: common.SkippedRepositories{
			AccessMismatchRepos: common.AccessMismatchRepos{
				RepositoryCount: 0,
				Repositories:    []common.Repository{},
			},
			NotFoundRepos: common.NotFoundRepos{
				RepositoryCount:     0,
				RepositoryFullNames: []string{},
			},
			NoCodeqlDBRepos: common.NoCodeqlDBRepos{
				RepositoryCount: 0,
				Repositories:    []common.Repository{},
			},
			OverLimitRepos: common.OverLimitRepos{
				RepositoryCount: 0,
				Repositories:    []common.Repository{},
			},
		},
	}

	scannedRepos := []common.ScannedRepo{}

	var jobStatus common.Status = common.StatusSucceeded

	status := common.StatusResponse{
		SessionId:            jsSessionID,
		ControllerRepo:       common.ControllerRepo{},
		Actor:                common.Actor{},
		QueryLanguage:        ji.QueryLanguage,
		QueryPackURL:         "", // FIXME
		CreatedAt:            ji.CreatedAt,
		UpdatedAt:            ji.UpdatedAt,
		ActionsWorkflowRunID: -1, // FIXME
		Status:               jobStatus.ToOverallStatusString(),
		ScannedRepositories:  scannedRepos,
		SkippedRepositories:  ji.SkippedRepositories,
	}

	// Encode the response as JSON
	submitStatus, err := json.Marshal(status)
	if err != nil {
		slog.Error("Error encoding response as JSON:",
			"error", err)
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	// Send analysisReposJSON via ResponseWriter
	w.Header().Set("Content-Type", "application/json")
	w.Write(submitStatus)
}

func (c *CommanderSingle) submitStatusResponse(w http.ResponseWriter, js common.JobSpec, ji common.JobInfo) {
	slog.Debug("Submitting status response", "job_id", js.SessionID)

	// Get the overall session status first to minimize race conditions
	// This ensures that if jobs complete after this point, the client will poll again
	sessionStatus, err := c.v.State.GetSessionStatus(js.SessionID)
	if err != nil {
		// Job rows may not all be visible yet (submit still in progress).
		// Report as pending so the client retries instead of seeing a 422.
		slog.Warn("Session status not yet available, reporting as pending", "session_id", js.SessionID, "error", err.Error())
		sessionStatus = common.StatusSummary{Overall: common.StatusPending, Counts: map[common.Status]int{}}
	}

	scannedRepos := []common.ScannedRepo{}

	jobs, err := c.v.State.GetJobList(js.SessionID)
	if err != nil {
		slog.Error("Error getting job list", "error", err.Error())
		http.Error(w, err.Error(), http.StatusUnprocessableEntity)
		return
	}

	// Loop through all jobs under the same session id
	for _, job := range jobs {

		// Get the job status
		status, err := c.v.State.GetStatus(job.Spec)
		if err != nil {
			// Status row not yet written (submit in progress). Treat as pending.
			slog.Warn("Job status not yet available, treating as pending", "job", job.Spec, "error", err.Error())
			status = common.StatusPending
		}

		// Get the job result if complete, otherwise return default values
		var artifactSize int
		var resultCount int

		if status != common.StatusSucceeded {
			// If the job is not successful, we don't need to get the result
			artifactSize = 0
			resultCount = 0
		} else {
			jobResult, err := c.v.State.GetResult(job.Spec)
			if err != nil {
				// Result row not yet written to Postgres by the agent.
				// Report as in-progress so the client retries.
				slog.Warn("Result not yet available for succeeded job, reporting as in-progress",
					"job", job.Spec, "error", err.Error())
				status = common.StatusInProgress
				artifactSize = 0
				resultCount = 0
			} else {
				artifactSize, err = c.v.Artifacts.GetResultSize(jobResult.ResultLocation)
				if err != nil {
					slog.Error("Error getting artifact size", "error", err.Error())
					http.Error(w, err.Error(), http.StatusUnprocessableEntity)
					return
				}
				resultCount = jobResult.ResultCount
			}
		}
		// Get jobRepoID from (owner,repo)
		jobRepoId := c.v.State.GetRepoId(job.Spec.NameWithOwner)

		// Append all scanned (complete and incomplete) repos to the response
		scannedRepos = append(scannedRepos,
			common.ScannedRepo{
				Repository: common.Repository{
					ID:              jobRepoId,
					Name:            job.Spec.Repo,
					FullName:        fmt.Sprintf("%s/%s", job.Spec.Owner, job.Spec.Repo),
					Private:         false,
					StargazersCount: 0,
					UpdatedAt:       ji.UpdatedAt,
				},
				AnalysisStatus:    status.ToRepoStatusString(),
				ResultCount:       resultCount,
				ArtifactSizeBytes: int(artifactSize),
			},
		)
	}

	status := common.StatusResponse{
		SessionId:            js.SessionID,
		ControllerRepo:       common.ControllerRepo{},
		Actor:                common.Actor{},
		QueryLanguage:        ji.QueryLanguage,
		QueryPackURL:         "", // FIXME
		CreatedAt:            ji.CreatedAt,
		UpdatedAt:            ji.UpdatedAt,
		ActionsWorkflowRunID: -1, // FIXME
		Status:               sessionStatus.Overall.ToOverallStatusString(),
		ScannedRepositories:  scannedRepos,
		SkippedRepositories:  ji.SkippedRepositories,
	}

	// Encode the response as JSON
	submitStatus, err := json.Marshal(status)
	if err != nil {
		slog.Error("Error encoding response as JSON:",
			"error", err)
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	// Send analysisReposJSON via ResponseWriter
	w.Header().Set("Content-Type", "application/json")
	w.Write(submitStatus)
}

func (c *CommanderSingle) RootHandler(w http.ResponseWriter, r *http.Request) {
	slog.Info("Request on /")

	// Get running jobs
	runningJobs, err := c.v.State.GetRunningJobs()
	if err != nil {
		slog.Error("Failed to get running jobs", "error", err)
		runningJobs = []queue.AnalyzeJob{}
	}

	// Get pending jobs count
	pendingJobs, err := c.v.State.GetPendingJobs()
	if err != nil {
		slog.Error("Failed to get pending jobs", "error", err)
		pendingJobs = []queue.AnalyzeJob{}
	}

	// Get recent sessions (last 30 days)
	recentSessions, err := c.v.State.GetRecentSessions(30)
	if err != nil {
		slog.Error("Failed to get recent sessions", "error", err)
		recentSessions = []state.SessionSummary{}
	}

	// Render HTML
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.WriteHeader(http.StatusOK)

	html := renderDashboard(runningJobs, pendingJobs, recentSessions, c.v.State)
	w.Write([]byte(html))
}

func formatAvgDuration(avgSeconds float64, completedJobs int) string {
	if completedJobs == 0 || avgSeconds <= 0 {
		return "N/A"
	}

	roundedSeconds := int64(avgSeconds + 0.5)
	if roundedSeconds < 1 {
		return "<1s"
	}

	d := time.Duration(roundedSeconds) * time.Second
	hours := int64(d.Hours())
	minutes := int64(d.Minutes()) % 60
	seconds := int64(d.Seconds()) % 60

	if hours > 0 {
		return fmt.Sprintf("%dh %dm %ds", hours, minutes, seconds)
	}
	if minutes > 0 {
		return fmt.Sprintf("%dm %ds", minutes, seconds)
	}
	return fmt.Sprintf("%ds", seconds)
}

func renderDashboard(runningJobs, pendingJobs []queue.AnalyzeJob, sessions []state.SessionSummary, st state.ServerState) string {
	// Build running jobs table rows
	runningRows := ""
	for _, job := range runningJobs {
		jobInfo, err := st.GetJobInfo(job.Spec)
		user := "N/A"
		workflowID := "N/A"
		startTime := "N/A"
		if err == nil {
			user = jobInfo.User
			if user == "" {
				user = "UNKNOWN"
			}
			workflowID = jobInfo.ArgoWorkflowID
			if workflowID == "" {
				workflowID = "pending"
			}
			startTime = jobInfo.StartedAt
		}

		runningRows += fmt.Sprintf(`
			<tr>
				<td>%s</td>
				<td>%d</td>
				<td>%s/%s</td>
				<td>%s</td>
				<td>%s</td>
				<td><code>%s</code></td>
			</tr>`,
			user,
			job.Spec.SessionID,
			job.Spec.Owner,
			job.Spec.Repo,
			job.QueryLanguage,
			startTime,
			workflowID,
		)
	}
	if runningRows == "" {
		runningRows = `<tr><td colspan="6" style="text-align: center; color: #666;">No jobs currently running</td></tr>`
	}

	// Build sessions table rows
	sessionRows := ""
	for _, sess := range sessions {
		statusClass := ""
		statusText := "Active"
		if sess.PendingJobs == 0 && sess.RunningJobs == 0 {
			if sess.CancelledJobs > 0 {
				statusClass = "status-cancelled"
				statusText = "Cancelled"
			} else {
				statusClass = "status-complete"
				statusText = "Complete"
			}
		} else if sess.RunningJobs > 0 {
			statusClass = "status-running"
			statusText = "Running"
		} else {
			statusClass = "status-pending"
			statusText = "Pending"
		}

		user := sess.User
		if user == "" {
			user = "UNKNOWN"
		}

		avgJobTime := formatAvgDuration(sess.AvgCompletedJobSeconds, sess.CompletedJobs)

		cancelButton := ""
		if sess.PendingJobs > 0 || sess.RunningJobs > 0 {
			cancelButton = fmt.Sprintf(
				`<button class="cancel-btn" onclick="cancelSession(%d)">Cancel</button>`,
				sess.SessionID)
		}

		sessionRows += fmt.Sprintf(`
			<tr>
				<td><a href="#" title="Session %d">%d</a></td>
				<td>%s</td>
				<td>%s</td>
				<td>%s</td>
				<td>%d</td>
				<td>%d</td>
				<td>%d</td>
				<td>%d</td>
				<td>%s</td>
				<td>%d</td>
				<td>%d</td>
				<td><span class="status %s">%s</span></td>
				<td>%s</td>
			</tr>`,
			sess.SessionID, sess.SessionID,
			user,
			sess.Language,
			sess.CreatedAt,
			sess.TotalJobs,
			sess.PendingJobs,
			sess.RunningJobs,
			sess.CompletedJobs,
			avgJobTime,
			sess.FailedJobs,
			sess.CancelledJobs,
			statusClass,
			statusText,
			cancelButton,
		)
	}
	if sessionRows == "" {
		sessionRows = `<tr><td colspan="13" style="text-align: center; color: #666;">No recent sessions</td></tr>`
	}

	// Calculate summary stats
	totalSessions := len(sessions)
	activeSessions := 0
	totalRunning := len(runningJobs)
	totalPending := len(pendingJobs)

	for _, sess := range sessions {
		if sess.PendingJobs > 0 || sess.RunningJobs > 0 {
			activeSessions++
		}
	}

	return fmt.Sprintf(`<!DOCTYPE html>
<html>
<head>
	<meta charset="UTF-8">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<meta http-equiv="refresh" content="30">
	<title>MRVA Commander Dashboard</title>
	<style>
		* {
			margin: 0;
			padding: 0;
			box-sizing: border-box;
		}
		body {
			font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
			background: #f5f5f5;
			color: #333;
			padding: 20px;
			line-height: 1.6;
		}
		.container {
			max-width: 1400px;
			margin: 0 auto;
		}
		h1 {
			color: #2c3e50;
			margin-bottom: 10px;
			font-size: 2em;
		}
		.subtitle {
			color: #7f8c8d;
			margin-bottom: 30px;
			font-size: 0.9em;
		}
		.stats {
			display: grid;
			grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
			gap: 15px;
			margin-bottom: 30px;
		}
		.stat-card {
			background: white;
			padding: 20px;
			border-radius: 8px;
			box-shadow: 0 2px 4px rgba(0,0,0,0.1);
		}
		.stat-card h3 {
			font-size: 0.85em;
			color: #7f8c8d;
			text-transform: uppercase;
			margin-bottom: 10px;
			font-weight: 600;
		}
		.stat-card .value {
			font-size: 2.5em;
			font-weight: 700;
			color: #2c3e50;
		}
		.stat-card.highlight .value {
			color: #3498db;
		}
		.section {
			background: white;
			border-radius: 8px;
			padding: 25px;
			margin-bottom: 25px;
			box-shadow: 0 2px 4px rgba(0,0,0,0.1);
		}
		.section h2 {
			color: #2c3e50;
			margin-bottom: 20px;
			font-size: 1.5em;
			border-bottom: 2px solid #3498db;
			padding-bottom: 10px;
		}
		table {
			width: 100%%;
			border-collapse: collapse;
		}
		th {
			background: #ecf0f1;
			padding: 12px;
			text-align: left;
			font-weight: 600;
			color: #2c3e50;
			font-size: 0.9em;
			text-transform: uppercase;
			letter-spacing: 0.5px;
		}
		td {
			padding: 12px;
			border-bottom: 1px solid #ecf0f1;
		}
		tr:hover {
			background: #f8f9fa;
		}
		code {
			background: #ecf0f1;
			padding: 2px 6px;
			border-radius: 3px;
			font-family: "SF Mono", Monaco, "Courier New", monospace;
			font-size: 0.9em;
		}
		.status {
			padding: 4px 12px;
			border-radius: 12px;
			font-size: 0.85em;
			font-weight: 600;
			display: inline-block;
		}
		.status-running {
			background: #e3f2fd;
			color: #1976d2;
		}
		.status-pending {
			background: #fff3e0;
			color: #f57c00;
		}
		.status-complete {
			background: #e8f5e9;
			color: #388e3c;
		}
		.status-cancelled {
			background: #fce4ec;
			color: #c2185b;
		}
		.cancel-btn {
			background: #e53935;
			color: white;
			border: none;
			padding: 4px 10px;
			border-radius: 4px;
			cursor: pointer;
			font-size: 12px;
		}
		.cancel-btn:hover {
			background: #b71c1c;
		}
		a {
			color: #3498db;
			text-decoration: none;
		}
		a:hover {
			text-decoration: underline;
		}
		.refresh-note {
			color: #7f8c8d;
			font-size: 0.85em;
			margin-top: 20px;
			text-align: center;
		}
		details.help-section {
			background: white;
			border-radius: 8px;
			padding: 15px 25px;
			margin-bottom: 25px;
			box-shadow: 0 2px 4px rgba(0,0,0,0.1);
		}
		details.help-section summary {
			cursor: pointer;
			font-weight: 600;
			color: #2c3e50;
			font-size: 1.1em;
			padding: 5px 0;
			list-style: revert;
		}
		details.help-section summary:hover {
			color: #3498db;
		}
		details.help-section .help-content {
			margin-top: 15px;
			line-height: 1.7;
			color: #444;
		}
		details.help-section .help-content ol {
			padding-left: 20px;
		}
		details.help-section .help-content li {
			margin-bottom: 12px;
		}
		details.help-section .help-content pre {
			background: #2c3e50;
			color: #ecf0f1;
			padding: 10px 14px;
			border-radius: 6px;
			overflow-x: auto;
			font-family: "SF Mono", Monaco, "Courier New", monospace;
			font-size: 0.88em;
			margin: 6px 0 4px 0;
		}
		details.help-section .help-content .alt-label {
			color: #7f8c8d;
			font-size: 0.92em;
		}
	</style>
</head>
<body>
	<div class="container">
		<h1>🚀 MRVA Commander Dashboard</h1>
		<p class="subtitle">Multi-Repository Variant Analysis System</p>
		
		<div class="stats">
			<div class="stat-card highlight">
				<h3>Running Jobs</h3>
				<div class="value">%d</div>
			</div>
			<div class="stat-card">
				<h3>Pending Jobs</h3>
				<div class="value">%d</div>
			</div>
			<div class="stat-card">
				<h3>Active Sessions</h3>
				<div class="value">%d</div>
			</div>
			<div class="stat-card">
				<h3>Total Sessions (30d)</h3>
				<div class="value">%d</div>
			</div>
		</div>

		<div class="section">
			<h2>Currently Running Jobs</h2>
			<table>
				<thead>
					<tr>
						<th>User</th>
						<th>Session</th>
						<th>Repository</th>
						<th>Language</th>
						<th>Started</th>
						<th>Argo Workflow ID</th>
					</tr>
				</thead>
				<tbody>
					%s
				</tbody>
			</table>
		</div>

		<details class="help-section">
			<summary>How to cancel an in-progress session</summary>
			<div class="help-content">
				<ol>
					<li>
						<strong>Install <code>gh-mrva</code></strong><br>
						From spaces:
						<pre>$ /opt/example/bin/apt-get install gh-mrva</pre>
						<span class="alt-label">From a dev machine:</span>
						<pre>$ cd some_temp_dir
$ /opt/example/bin/dpkg-distro-dev init .
$ /opt/example/bin/dpkg-distro-dev install gh-mrva
$ /opt/example/bin/dpkg-distro-dev run gh-mrva</pre>
					</li>
					<li>
						<strong>Acquire Kerberos credentials</strong>
						<pre>$ kinit</pre>
					</li>
					<li>
						<strong>Cancel the session</strong><br>
						Use <code>gh-mrva</code> to cancel the listed variant analysis session:
						<pre>$ gh-mrva cancel -r &lt;session id&gt;</pre>
					</li>
				</ol>
			</div>
		</details>

		<div class="section">
			<h2>Recent Variant Analysis Sessions</h2>
			<table>
				<thead>
					<tr>
						<th>Session</th>
						<th>User</th>
						<th>Language</th>
						<th>Created</th>
						<th>Total</th>
						<th>Pending</th>
						<th>Running</th>
						<th>Complete</th>
						<th>Avg Job Time</th>
						<th>Failed</th>
						<th>Cancelled</th>
						<th>Status</th>
						<th>Actions</th>
					</tr>
				</thead>
				<tbody>
					%s
				</tbody>
			</table>
		</div>

		<p class="refresh-note">⟳ Auto-refreshing every 30 seconds | Last updated: <script>document.write(new Date().toLocaleString())</script></p>
	</div>
	<script>
	(function() {
		var d = document.querySelector('details.help-section');
		if (!d) return;
		if (localStorage.getItem('help-section-open') === 'true') d.open = true;
		d.addEventListener('toggle', function() {
			localStorage.setItem('help-section-open', d.open);
		});
	})();
	function cancelSession(sessionId) {
		if (!confirm('Cancel session ' + sessionId + '? This will stop all pending and running jobs.')) return;
		fetch('/repositories/0/code-scanning/codeql/variant-analyses/' + sessionId + '/cancel', {
			method: 'POST'
		}).then(function(resp) {
			if (resp.ok) {
				alert('Session ' + sessionId + ' cancelled.');
				location.reload();
			} else {
				resp.text().then(function(t) { alert('Cancel failed: ' + t); });
			}
		}).catch(function(err) { alert('Cancel failed: ' + err); });
	}
	</script>
</body>
</html>`,
		totalRunning,
		totalPending,
		activeSessions,
		totalSessions,
		runningRows,
		sessionRows,
	)
}

func (c *CommanderSingle) CancelVariantAnalysis(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	runID := vars["run_id"]

	slog.Info("Cancel variant analysis request", "run_id", runID)

	// Parse run_id as session ID
	sessionID, err := strconv.Atoi(runID)
	if err != nil {
		slog.Error("Invalid run_id", "run_id", runID, "error", err)
		http.Error(w, "Invalid run_id: must be an integer", http.StatusBadRequest)
		return
	}

	// Get the user from context
	user, ok := UserFromContext(r.Context())
	if !ok {
		slog.Error("Could not extract user from context")
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}

	// Verify the session exists and belongs to this user
	jobs, err := c.v.State.GetJobList(sessionID)
	if err != nil || len(jobs) == 0 {
		slog.Error("Session not found", "session_id", sessionID, "error", err)
		http.Error(w, "Session not found", http.StatusNotFound)
		return
	}

	// Get first job to check user ownership
	firstJobInfo, err := c.v.State.GetJobInfo(jobs[0].Spec)
	if err != nil {
		slog.Error("Could not get job info for verification", "session_id", sessionID, "error", err)
		http.Error(w, "Internal error", http.StatusInternalServerError)
		return
	}

	// Verify the user owns this session
	if firstJobInfo.User != user && user != "UNKNOWN" {
		slog.Warn("User attempted to cancel another user's session",
			"requesting_user", user,
			"session_owner", firstJobInfo.User,
			"session_id", sessionID)
		http.Error(w, "Forbidden: you can only cancel your own sessions", http.StatusForbidden)
		return
	}

	// Cancel all pending/running jobs in the database
	pendingCancelled, err := c.v.State.CancelSession(sessionID)
	if err != nil {
		slog.Error("Error cancelling session jobs", "session_id", sessionID, "error", err)
		http.Error(w, "Error cancelling session", http.StatusInternalServerError)
		return
	}

	// Cancel running workflows via pool manager
	runningCancelled := 0
	runningCancelled, err = c.v.PoolManager.CancelRunningJobsForSession(sessionID)
	if err != nil {
		slog.Error("Error cancelling running workflows", "session_id", sessionID, "error", err)
		// Continue anyway to cancel pending jobs
	} else {
		slog.Info("Cancelled running workflows", "session_id", sessionID, "count", runningCancelled)
	}

	totalCancelled := runningCancelled + pendingCancelled
	slog.Info("Variant analysis cancelled",
		"session_id", sessionID,
		"user", user,
		"running_cancelled", runningCancelled,
		"pending_cancelled", pendingCancelled,
		"total_cancelled", totalCancelled)

	// Return success response
	response := map[string]interface{}{
		"message":           "Variant analysis cancelled successfully",
		"session_id":        sessionID,
		"cancelled_jobs":    totalCancelled,
		"running_cancelled": runningCancelled,
		"pending_cancelled": pendingCancelled,
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(response)
}

func (c *CommanderSingle) MRVAStatusCommon(w http.ResponseWriter, r *http.Request, owner, repo string, variantAnalysisID string) {
	slog.Info("MRVA status request for ",
		"owner", owner,
		"repo", repo,
		"codeql_variant_analysis_id", variantAnalysisID)

	sessionId, err := strconv.ParseInt(variantAnalysisID, 10, 32)
	if err != nil {
		slog.Error("Variant analysis ID is not integer", "id",
			variantAnalysisID)
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	jobs, err := c.v.State.GetJobList(int(sessionId))
	if err != nil {
		msg := "No jobs found for given session id"
		slog.Error(msg, "id", variantAnalysisID)
		http.Error(w, msg, http.StatusNotFound)
		return
	}
	if len(jobs) == 0 {
		c.submitEmptyStatusResponse(w, int(sessionId))
		return
	}

	// Get session-level metadata (language, timestamps, skipped repos) from any job
	// All jobs in a session share this metadata, so we arbitrarily pick the first one
	job := jobs[0]

	jobInfo, err := c.v.State.GetJobInfo(job.Spec)
	if err != nil {
		msg := "No job info found for given session id"
		slog.Error(msg, "id", variantAnalysisID)
		http.Error(w, msg, http.StatusBadRequest)
		return
	}

	c.submitStatusResponse(w, job.Spec, jobInfo)

}

func (c *CommanderSingle) MRVAStatusID(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	slog.Info("MRVA status request (MRVAStatusID)")
	// Mapping to unused/unused and passing variant analysis id
	c.MRVAStatusCommon(w, r, "unused", "unused", vars["codeql_variant_analysis_id"])
}

func (c *CommanderSingle) MRVAStatus(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	slog.Info("MRVA status request (MRVAStatus)")
	// Mapping to owner/repo and passing variant analysis id
	c.MRVAStatusCommon(w, r, vars["owner"], vars["repo"], vars["codeql_variant_analysis_id"])
}

// Download artifacts
func (c *CommanderSingle) MRVADownloadArtifactCommon(w http.ResponseWriter,
	r *http.Request, jobRepoId int, jobSpec common.JobSpec) {
	slog.Debug("MRVA artifact download",
		"codeql_variant_analysis_id", jobSpec.SessionID,
		"repo_owner", jobSpec.NameWithOwner.Owner,
		"repo_name", jobSpec.NameWithOwner.Repo,
		"jobRepoId", jobRepoId,
	)

	c.sendArtifactDownloadResponse(w, r, jobRepoId, jobSpec)
}

func (c *CommanderSingle) MRVADownloadArtifactID(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	slog.Debug("MRVA artifact download", "id", vars["codeql_variant_analysis_id"], "repo_id", vars["repository_id"])

	sessionId, err := strconv.ParseInt(vars["codeql_variant_analysis_id"], 10, 32)
	if err != nil {
		slog.Error("Variant analysis ID is not an integer", "id", vars["codeql_variant_analysis_id"])
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	// this must match the repo ID returned by the status request
	repoId, err := strconv.ParseInt(vars["repository_id"], 10, 32)
	if err != nil {
		slog.Error("Repository ID is not an integer", "id", vars["repository_id"])
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	jobSpec, err := c.v.State.GetJobSpecByRepoId(int(sessionId), int(repoId))
	if err != nil {
		slog.Error("Failed to get job spec by repo ID", "error", err)
		http.Error(w, err.Error(), http.StatusUnprocessableEntity)
		return
	}

	c.MRVADownloadArtifactCommon(w, r, int(repoId), jobSpec)
}

func (c *CommanderSingle) MRVADownloadQLDB(w http.ResponseWriter, r *http.Request) {
	// The repositories are uploaded without language and can be downloaded
	// without it.  We ignore the language parameter passed in the request:
	// vars["repo_language"]

	// Other artifact downloads, like sendArtifactDownloadResponse, depend on
	// a jobspec (integer job id).  This request has none, and needs none.

	// An original upload example is
	//		tdlib$telegram-bot-apictsj8529d9.zip to bucket qldb.

	// This is a direct data request -- don't reply with a download url.

	vars := mux.Vars(r)
	dbl := common.NameWithOwner{
		Owner: vars["repo_owner"],
		Repo:  vars["repo_name"],
	}
	language := vars["repo_language"]

	slog.Debug("Returning codeql database using database location",
		"dbl", dbl,
		"language", language,
	)

	dbContent, err := c.v.CodeQLDBStore.GetDatabase(dbl, language)
	if err != nil {
		slog.Error("Failed to retrieve ql database",
			"error", err,
			"dbl", dbl,
		)
		http.Error(w, "Failed to retrieve ql database", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/octet-stream")
	w.Write(dbContent)

}

func (c *CommanderSingle) MRVADownloadArtifact(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)

	sessionId, err := strconv.ParseInt(vars["codeql_variant_analysis_id"], 10, 32)
	if err != nil {
		slog.Error("Variant analysis ID is not an integer", "id", vars["codeql_variant_analysis_id"])
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	jobSpec := common.JobSpec{
		SessionID: int(sessionId),
		NameWithOwner: common.NameWithOwner{
			Owner: vars["repo_owner"],
			Repo:  vars["repo_name"],
		},
	}
	// TODO: THIS IS BROKEN UNLESS REPO ID IS IGNORED
	c.MRVADownloadArtifactCommon(w, r, -1, jobSpec)
}

func (c *CommanderSingle) sendArtifactDownloadResponse(w http.ResponseWriter, r *http.Request,
	jobRepoId int, jobSpec common.JobSpec) {
	var response common.DownloadResponse

	slog.Debug("Forming download response", "job", jobSpec)

	jobStatus, err := c.v.State.GetStatus(jobSpec)
	if err != nil {
		slog.Error(err.Error())
		http.Error(w, err.Error(), http.StatusUnprocessableEntity)
		return
	}

	if jobStatus == common.StatusSucceeded {
		jobResult, err := c.v.State.GetResult(jobSpec)
		if err != nil {
			slog.Error(err.Error())
			http.Error(w, err.Error(), http.StatusUnprocessableEntity)
			return
		}

		jobResultData, err := c.v.Artifacts.GetResult(jobResult.ResultLocation)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}

		// Generate the artifact URL
		encodedJobSpec, err := common.EncodeJobSpec(jobSpec)
		if err != nil {
			http.Error(w, "Failed to encode job spec", http.StatusInternalServerError)
			return
		}

		url := os.Getenv("MRVA_SERVER_URL")
		if url == "" {
			// Extract base URL from the incoming request
			scheme := "https"
			url = fmt.Sprintf("%s://%s", scheme, r.Host)
			slog.Debug("MRVA_SERVER_URL not set, using request host", "url", url)
		}

		artifactURL := fmt.Sprintf("%s/download/%s", url, encodedJobSpec)

		response = common.DownloadResponse{
			Repository: common.DownloadRepo{
				// TODO: fix jobRepoID coming from the NWO path. The MRVA extension uses repo ID.
				ID:       jobRepoId,
				Name:     jobSpec.Repo,
				FullName: fmt.Sprintf("%s/%s", jobSpec.Owner, jobSpec.Repo),
			},
			AnalysisStatus:       jobStatus.ToRepoStatusString(),
			ResultCount:          jobResult.ResultCount,
			ArtifactSizeBytes:    len(jobResultData),
			DatabaseCommitSha:    jobResult.DatabaseSHA,
			SourceLocationPrefix: jobResult.SourceLocationPrefix,
			ArtifactURL:          artifactURL,
		}
	} else {
		// not successful status
		response = common.DownloadResponse{
			Repository: common.DownloadRepo{
				// TODO: fix jobRepoID coming from the NWO path. The MRVA extension uses repo ID.
				ID:       jobRepoId,
				Name:     jobSpec.Repo,
				FullName: fmt.Sprintf("%s/%s", jobSpec.Owner, jobSpec.Repo),
			},
			AnalysisStatus:       jobStatus.ToRepoStatusString(),
			ResultCount:          0,
			ArtifactSizeBytes:    0,
			DatabaseCommitSha:    "",
			SourceLocationPrefix: "",
			ArtifactURL:          "",
		}
	}

	// Encode the response as JSON
	responseJson, err := json.Marshal(response)
	if err != nil {
		slog.Error("Error encoding response as JSON:",
			"error", err)
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	slog.Debug("MRVA: Sending download response", "responseJson", responseJson)

	// Send analysisReposJSON via ResponseWriter
	w.Header().Set("Content-Type", "application/json")
	w.Write(responseJson)
}

func (c *CommanderSingle) MRVADownloadServe(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	encodedJobSpec := vars["encoded_job_spec"]

	jobSpec, err := common.DecodeJobSpec(encodedJobSpec)
	if err != nil {
		http.Error(w, "Invalid job spec", http.StatusBadRequest)
		return
	}

	slog.Info("Result download request", "job_spec", jobSpec)

	result, err := c.v.State.GetResult(jobSpec)
	if err != nil {
		slog.Error("Failed to get result", "error", err)
		http.Error(w, "Failed to get result", http.StatusInternalServerError)
		return
	}

	slog.Debug("Result location", "location", result.ResultLocation)

	data, err := c.v.Artifacts.GetResult(result.ResultLocation)
	if err != nil {
		slog.Error("Failed to retrieve artifact", "error", err)
		http.Error(w, "Failed to retrieve artifact", http.StatusInternalServerError)
		return
	}

	// Send the file as a response
	w.Header().Set("Content-Type", "application/octet-stream")
	w.Write(data)
}

func (c *CommanderSingle) MRVARequestCommon(w http.ResponseWriter, r *http.Request) {
	// This request is slow - slower than the BPaaS timeout
	// We need to prevent BPaaS from closing the connection by
	// sending data down it periodically. We try to solve that
	// here by sending whitespace bytes before the json response.

	// Make sure we can flush
	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming unsupported", http.StatusInternalServerError)
		return
	}

	sessionId := c.v.State.NextID()
	slog.Info("New MRVA Request", "id", sessionId)
	user, _ := UserFromContext(r.Context())
	// HTTP/1 responses can close an unread request body, especially with Expect: 100-continue.
	queryLanguage, repoNWOs, queryPackLocation, packSHA1, err := c.collectRequestInfoAndSaveQueryPack(r, sessionId)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	// Prepare response headers up front
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("X-Accel-Buffering", "no") // tell nginx not to buffer

	// Start the response and push a padding chunk so nginx forwards it
	w.WriteHeader(http.StatusOK)
	// Leading whitespace is allowed before a JSON value
	_, _ = w.Write([]byte(strings.Repeat(" ", 1024) + "\n"))
	flusher.Flush()

	// Heartbeat ticker to prevent 60s of silence
	hb := time.NewTicker(25 * time.Second)
	defer hb.Stop()

	// Run slow work concurrently; we’ll keep the line alive
	type result struct {
		data []byte
		err  error
	}
	done := make(chan result, 1)

	go func() {
		notFoundRepos, analysisRepos := c.v.CodeQLDBStore.FindAvailableDBs(repoNWOs, string(queryLanguage))
		c.startAnalyses(analysisRepos, queryPackLocation, sessionId, queryLanguage, user)

		sessionInfo := SessionInfo{
			ID:                  sessionId,
			QueryPack:           strconv.Itoa(sessionId),
			PackSHA1:            packSHA1,
			Language:            queryLanguage,
			User:                user,
			AccessMismatchRepos: nil,
			NotFoundRepos:       notFoundRepos,
			NoCodeqlDBRepos:     nil,
		}

		b, err := c.buildSessionInfoResponseJson(sessionInfo)
		done <- result{b, err}
	}()

	// Keep sending tiny heartbeats until we get a result or the client goes away
	for {
		select {
		case <-r.Context().Done():
			// client disconnected
			slog.Warn("client canceled submit")
			return
		case <-hb.C:
			// newline heartbeat
			_, _ = w.Write([]byte("\n"))
			flusher.Flush()
		case res := <-done:
			if res.err != nil {
				http.Error(w, res.err.Error(), http.StatusBadRequest)
				return
			}
			// Now write the real JSON payload and finish
			_, _ = w.Write(res.data)
			flusher.Flush()
			return
		}
	}
}

func (c *CommanderSingle) MRVARequestID(w http.ResponseWriter, r *http.Request) {
	slog.Debug("MRVARequestID")
	c.MRVARequestCommon(w, r)
}

func (c *CommanderSingle) MRVARequest(w http.ResponseWriter, r *http.Request) {
	slog.Debug("MRVARequest")
	c.MRVARequestCommon(w, r)
}

func nwoToNwoStringArray(nwo []common.NameWithOwner) ([]string, int) {
	repos := []string{}
	count := len(nwo)
	for _, repo := range nwo {
		repos = append(repos, fmt.Sprintf("%s/%s", repo.Owner, repo.Repo))
	}
	return repos, count
}

func nwoToDummyRepositoryArray(nwo []common.NameWithOwner) ([]common.Repository, int) {
	repos := []common.Repository{}
	for _, repo := range nwo {
		repos = append(repos, common.Repository{
			ID:              -1,
			Name:            repo.Repo,
			FullName:        fmt.Sprintf("%s/%s", repo.Owner, repo.Repo),
			Private:         false,
			StargazersCount: 0,
			UpdatedAt:       time.Now().Format(time.RFC3339),
		})
	}
	count := len(nwo)

	return repos, count
}

// ConsumeResults moves results from 'queue' to server 'state'
func (c *CommanderSingle) ConsumeResults() {
	slog.Info("Started server results consumer.")
	for {
		r := <-c.v.Queue.Results()
		slog.Debug("Result consumed:", "r", r, "status", r.Status.ToExternalString())
		c.v.State.SetResultAndStatus(r.Spec, r, r.Status)

		// Trigger pool manager to wake up and potentially queue more work
		// now that a job has completed and state has changed
		c.v.PoolManager.TriggerScheduling()
	}
}

func (c *CommanderSingle) buildSessionInfoResponseJson(si SessionInfo) ([]byte, error) {
	// Construct the response bottom-up
	var controllerRepo common.ControllerRepo
	var actor common.Actor

	repoNames, count := nwoToNwoStringArray(si.NotFoundRepos)
	notFoundRepos := common.NotFoundRepos{RepositoryCount: count, RepositoryFullNames: repoNames}

	repos, _ := nwoToDummyRepositoryArray(si.AccessMismatchRepos)
	accessMismatchRepos := common.AccessMismatchRepos{RepositoryCount: count, Repositories: repos}

	repos, _ = nwoToDummyRepositoryArray(si.NoCodeqlDBRepos)
	noCodeQLDBRepos := common.NoCodeqlDBRepos{RepositoryCount: count, Repositories: repos}

	// TODO fill these with real values?
	repos, _ = nwoToDummyRepositoryArray(si.NoCodeqlDBRepos)
	overlimitRepos := common.OverLimitRepos{RepositoryCount: 0, Repositories: repos}

	skippedRepositories := common.SkippedRepositories{
		AccessMismatchRepos: accessMismatchRepos,
		NotFoundRepos:       notFoundRepos,
		NoCodeqlDBRepos:     noCodeQLDBRepos,
		OverLimitRepos:      overlimitRepos}

	response := common.SubmitResponse{
		Actor:               actor,
		ControllerRepo:      controllerRepo,
		ID:                  si.ID,
		QueryLanguage:       string(si.Language),
		QueryPackURL:        si.QueryPack,
		CreatedAt:           time.Now().Format(time.RFC3339),
		UpdatedAt:           time.Now().Format(time.RFC3339),
		Status:              "in_progress",
		SkippedRepositories: skippedRepositories,
	}

	// Store data needed later
	joblist, err := c.v.State.GetJobList(si.ID)
	if err != nil {
		slog.Error("Error getting job list", "error", err.Error())
		return nil, err
	}

	for _, job := range joblist {
		c.v.State.SetJobInfo(common.JobSpec{
			SessionID:     si.ID,
			NameWithOwner: job.Spec.NameWithOwner,
		}, common.JobInfo{
			QueryLanguage:       string(si.Language),
			CreatedAt:           response.CreatedAt,
			UpdatedAt:           response.UpdatedAt,
			User:                si.User,
			PackSHA1:            si.PackSHA1,
			ArgoWorkflowID:      "", // Will be set by worker when job is claimed
			StartedAt:           "", // Will be set by worker when job starts
			CompletedAt:         "", // Will be set when job completes
			SkippedRepositories: skippedRepositories,
		},
		)
	}

	// Encode the response as JSON
	responseJson, err := json.Marshal(response)
	if err != nil {
		slog.Error("Error encoding response as JSON", "err", err)
		return nil, err
	}
	return responseJson, nil

}

func (c *CommanderSingle) collectRequestInfoAndSaveQueryPack(r *http.Request, sessionId int) (queue.QueryLanguage, []common.NameWithOwner, artifactstore.ArtifactLocation, string, error) {
	slog.Debug("Collecting session info")

	if r.Body == nil {
		err := errors.New("missing request body")
		slog.Error("Error reading MRVA submission body", "error", err)
		return "", []common.NameWithOwner{}, artifactstore.ArtifactLocation{}, "", err
	}

	buf, err := io.ReadAll(r.Body)
	if err != nil {
		slog.Error("Error reading MRVA submission body", "error", err)
		return "", []common.NameWithOwner{}, artifactstore.ArtifactLocation{}, "", err
	}

	msg, err := tryParseSubmitMsg(buf)
	if err != nil {
		slog.Error("Unknown MRVA submission body format", "err", err)
		return "", []common.NameWithOwner{}, artifactstore.ArtifactLocation{}, "", err
	}

	var sessionRepos []common.NameWithOwner
	for _, repository := range msg.Repositories {
		parts := strings.Split(repository, "/")
		if len(parts) != 2 || parts[0] == "" || parts[1] == "" {
			err := fmt.Errorf("invalid owner/repository entry: %q", repository)
			slog.Error("Invalid MRVA submission repository", "error", err)
			return "", nil, artifactstore.ArtifactLocation{}, "", err
		}
		sessionRepos = append(sessionRepos, common.NameWithOwner{Owner: parts[0], Repo: parts[1]})
	}

	// 1. Save the query pack and keep the location
	if !utils.IsBase64Gzip([]byte(msg.QueryPack)) {
		slog.Error("MRVA submission body querypack has invalid format")
		err := errors.New("MRVA submission body querypack has invalid format")
		return "", []common.NameWithOwner{}, artifactstore.ArtifactLocation{}, "", err
	}

	queryPackLocation, packSHA1, err := c.decodeAndSaveBase64QueryPack(msg.QueryPack, sessionId)
	if err != nil {
		slog.Error("Error processing query pack archive", "error", err)
		return "", []common.NameWithOwner{}, artifactstore.ArtifactLocation{}, "", err
	}

	// 2. Save the language
	sessionLanguage := queue.QueryLanguage(msg.Language)

	return sessionLanguage, sessionRepos, queryPackLocation, packSHA1, nil
}

// Try to extract a SubmitMsg from a json-encoded buffer
func tryParseSubmitMsg(buf []byte) (common.SubmitMsg, error) {
	buf1 := make([]byte, len(buf))
	copy(buf1, buf)
	dec := json.NewDecoder(bytes.NewReader(buf1))
	dec.DisallowUnknownFields()
	var m common.SubmitMsg
	err := dec.Decode(&m)
	return m, err
}

// decodeAndSaveBase64QueryPack decodes, persists, and fingerprints the query
// pack. The returned SHA1 (hex) is computed over the decoded pack bytes as they
// arrive at the server; it is the pack's shared identity across sessions (the
// submission carries no pack name), surfaced in the sysview as "pack-<sha1>".
func (c *CommanderSingle) decodeAndSaveBase64QueryPack(qp string, sessionId int) (artifactstore.ArtifactLocation, string, error) {
	// These are decoded manually via
	//    base64 -d < foo1 | gunzip | tar t | head -20
	// base64 decode the body
	slog.Debug("Extracting query pack")

	tgz, err := base64.StdEncoding.DecodeString(qp)
	if err != nil {
		slog.Error("Failed to decode query pack body", "err", err)
		return artifactstore.ArtifactLocation{}, "", err
	}

	sum := sha1.Sum(tgz)
	packSHA1 := hex.EncodeToString(sum[:])

	artifactLocation, err := c.v.Artifacts.SaveQueryPack(sessionId, tgz)
	if err != nil {
		slog.Error("Failed to save query pack", "err", err)
		return artifactstore.ArtifactLocation{}, "", err
	}

	return artifactLocation, packSHA1, err
}
