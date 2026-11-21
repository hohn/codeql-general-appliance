package scheduler

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"os/exec"
	"sync"
	"syscall"
	"time"

	"github.com/hohn/mrvacommander/pkg/queue"
)

// LocalArgoClient implements ArgoWorkflowClient by spawning local OS processes
// instead of submitting Argo Workflows. Used for local development via envsim.
type LocalArgoClient struct {
	agentBinaryPath string
	mu              sync.Mutex
	processes       map[string]*localProcess
}

type localProcess struct {
	id      string
	cmd     *exec.Cmd
	done    chan struct{} // closed when process exits
	exitErr error        // populated after process exits
}

// NewLocalArgoClient creates a LocalArgoClient that spawns agent-commander-argo
// as local processes. Requires MRVA_ENVSIM_AGENT_BINARY to be set.
func NewLocalArgoClient() (*LocalArgoClient, error) {
	binaryPath := os.Getenv("MRVA_ENVSIM_AGENT_BINARY")
	if binaryPath == "" {
		return nil, fmt.Errorf("MRVA_ENVSIM_AGENT_BINARY must be set to the path of the agent-commander-argo binary")
	}

	if _, err := os.Stat(binaryPath); err != nil {
		return nil, fmt.Errorf("agent binary not found at %s: %w", binaryPath, err)
	}

	slog.Info("LocalArgoClient initialized", "agent_binary", binaryPath)

	return &LocalArgoClient{
		agentBinaryPath: binaryPath,
		processes:       make(map[string]*localProcess),
	}, nil
}

// SubmitWorkflow spawns a local agent-commander-argo process in pool mode.
// The agent inherits all parent env vars and will claim jobs from PostgreSQL.
func (c *LocalArgoClient) SubmitWorkflow(job queue.AnalyzeJob) (string, error) {
	processID := fmt.Sprintf("envsim-%d", time.Now().UnixNano())

	cmd := exec.Command(c.agentBinaryPath, "--loglevel=debug")

	// Inherit parent environment so the agent gets all POSTGRES_*, MRVA_RABBITMQ_*,
	// MRVA_BCS_*, MRVA_HEPC_* vars. Ensure the spawned agent exits promptly after
	// completing work: default its idle timeout to 30s, but only when the parent
	// has not already set MRVA_POOL_IDLE_TIMEOUT_SECONDS (so local runs and the
	// test harness retain full override flexibility). Note exec.Cmd.Env uses the
	// last value for a duplicate key, so an unconditional append would silently
	// override any inherited value.
	cmd.Env = os.Environ()
	if os.Getenv("MRVA_POOL_IDLE_TIMEOUT_SECONDS") == "" {
		cmd.Env = append(cmd.Env, "MRVA_POOL_IDLE_TIMEOUT_SECONDS=30")
	}
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Start(); err != nil {
		return "", fmt.Errorf("failed to start agent process: %w", err)
	}

	proc := &localProcess{
		id:   processID,
		cmd:  cmd,
		done: make(chan struct{}),
	}

	// Monitor process in background
	go func() {
		proc.exitErr = cmd.Wait()
		close(proc.done)

		if proc.exitErr != nil {
			slog.Warn("Agent process exited with error",
				"process_id", processID,
				"pid", cmd.Process.Pid,
				"error", proc.exitErr)
		} else {
			slog.Info("Agent process exited successfully",
				"process_id", processID,
				"pid", cmd.Process.Pid)
		}
	}()

	c.mu.Lock()
	c.processes[processID] = proc
	c.mu.Unlock()

	slog.Info("Spawned local agent process",
		"process_id", processID,
		"pid", cmd.Process.Pid,
		"session_id", job.Spec.SessionID,
		"owner", job.Spec.Owner,
		"repo", job.Spec.Repo)

	// Return JSON metadata consistent with ArgoClient's format
	metadata := WorkflowMetadata{
		Name:    processID,
		UID:     processID,
		Cluster: "local",
	}
	metadataJSON, err := json.Marshal(metadata)
	if err != nil {
		return "", fmt.Errorf("failed to marshal process metadata: %w", err)
	}

	return string(metadataJSON), nil
}

// GetWorkflowStatus checks if a local agent process is running, succeeded, or failed.
func (c *LocalArgoClient) GetWorkflowStatus(workflowMetadataJSON string) (string, error) {
	var metadata WorkflowMetadata
	if err := json.Unmarshal([]byte(workflowMetadataJSON), &metadata); err != nil {
		return "", fmt.Errorf("invalid workflow metadata: %w", err)
	}

	c.mu.Lock()
	proc, exists := c.processes[metadata.Name]
	c.mu.Unlock()

	if !exists {
		return "", fmt.Errorf("process %s not found", metadata.Name)
	}

	select {
	case <-proc.done:
		if proc.exitErr != nil {
			return "Failed", nil
		}
		return "Succeeded", nil
	default:
		return "Running", nil
	}
}

// CancelWorkflow sends SIGTERM to a local agent process, then SIGKILL after 5 seconds.
func (c *LocalArgoClient) CancelWorkflow(workflowMetadataJSON string) (bool, error) {
	var metadata WorkflowMetadata
	if err := json.Unmarshal([]byte(workflowMetadataJSON), &metadata); err != nil {
		return false, fmt.Errorf("invalid workflow metadata: %w", err)
	}

	c.mu.Lock()
	proc, exists := c.processes[metadata.Name]
	c.mu.Unlock()

	if !exists {
		return true, nil // already gone
	}

	select {
	case <-proc.done:
		return true, nil // already exited
	default:
		if proc.cmd.Process != nil {
			slog.Info("Sending SIGTERM to agent process",
				"process_id", metadata.Name,
				"pid", proc.cmd.Process.Pid)
			proc.cmd.Process.Signal(syscall.SIGTERM)

			// Wait briefly, then force kill
			select {
			case <-proc.done:
				// exited gracefully
			case <-time.After(5 * time.Second):
				slog.Warn("Agent process did not exit after SIGTERM, sending SIGKILL",
					"process_id", metadata.Name)
				proc.cmd.Process.Kill()
			}
		}
		return true, nil
	}
}

// Cleanup kills all tracked agent processes. Call on server shutdown.
func (c *LocalArgoClient) Cleanup() {
	c.mu.Lock()
	defer c.mu.Unlock()

	for id, proc := range c.processes {
		select {
		case <-proc.done:
			// already exited
		default:
			if proc.cmd.Process != nil {
				slog.Info("Cleanup: killing agent process", "process_id", id, "pid", proc.cmd.Process.Pid)
				proc.cmd.Process.Kill()
			}
		}
	}
}
