package scheduler

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"os"
	"sync"
	"time"

	"github.com/hohn/mrvacommander/pkg/queue"
)

// ArgoWorkflowClient defines the interface for interacting with Argo Workflows.
// Implementations submit and track worker workflows (or local worker processes)
// on behalf of the pool manager.
type ArgoWorkflowClient interface {
	// SubmitWorkflow schedules a new workflow and returns its UID
	SubmitWorkflow(job queue.AnalyzeJob) (workflowUID string, err error)

	// GetWorkflowStatus checks the status of a running workflow by its UID
	GetWorkflowStatus(workflowUID string) (status string, err error)

	// CancelWorkflow attempts to cancel a running workflow
	// Returns true if the workflow was successfully cancelled or is already complete
	CancelWorkflow(workflowID string) (cancelled bool, err error)
}

// ArgoClient implements ArgoWorkflowClient for Argo Workflows
type ArgoClient struct {
	// Configuration
	tier                string
	namespace           string
	argoAPIBaseURL      string
	proxyURL            string
	identityExchangeURL string

	// Environment variables for workflow
	codeqlCLIPath     string
	bcsEndpoint       string
	bucket            string
	hepcEndpoint      string
	hepcCacheDuration string
	hepcDataViaCLI    string
	hepcOutDir        string
	hepcTool          string
	postgresUser      string
	postgresPassword  string
	postgresHost      string
	postgresPort      string
	postgresDB        string
	postgresCACert    string // PEM content of the CA certificate
	codeqlRAMMB       string
	codeqlThreads     string

	// HTTP client
	httpClient *http.Client

	// Token management
	tokenMutex   sync.RWMutex
	currentToken string
	tokenExpiry  time.Time

	// ADPRD credentials
	adprdUser     string
	adprdPassword string
}

// ArgoClientConfig holds configuration for the Argo client
type ArgoClientConfig struct {
	Tier                string
	Namespace           string
	ArgoAPIBaseURL      string
	ProxyURL            string
	IdentityExchangeURL string
	CodeQLCLIPath       string
	BCSEndpoint         string
	Bucket              string
	HEPCEndpoint        string
	HEPCCacheDuration   string
	HEPCDataViaCLI      string
	HEPCOutDir          string
	HEPCTool            string
	PostgresUser        string
	PostgresPassword    string
	PostgresHost        string
	PostgresPort        string
	PostgresDB          string
	PostgresCACert      string // PEM content of the CA certificate

	CodeQLRAMMB   string
	CodeQLThreads string

	ADPRDUser     string
	ADPRDPassword string
}

// NewArgoClientFromEnv creates a new ArgoClient from environment variables
func NewArgoClientFromEnv() (*ArgoClient, error) {
	tier := os.Getenv("MRVA_TIER")
	if tier == "" {
		tier = "dev" // default to dev
	}

	// Pool mode is the only supported execution model: agents claim jobs
	// from PostgreSQL and persist results back to it. MRVA_POOL_MODE is
	// obsolete; warn if it is still set so operators can remove it.
	if _, ok := os.LookupEnv("MRVA_POOL_MODE"); ok {
		slog.Warn("MRVA_POOL_MODE is obsolete and ignored; pool mode is always enabled")
	}

	config := ArgoClientConfig{
		Tier:                tier,
		Namespace:           getEnvOrDefault("MRVA_ARGO_NAMESPACE", "s-product-security-mrva"),
		ArgoAPIBaseURL:      getEnvOrDefault("MRVA_ARGO_API_URL", "https://workflows.cncr-api.prod.example.com/api/v1"),
		ProxyURL:            getEnvOrDefault("MRVA_ARGO_PROXY", "http://bproxy.tdmz1.example.com:80"),
		IdentityExchangeURL: getEnvOrDefault("MRVA_IDENTITY_EXCHANGE_URL", "https://identity-exchange.dna.prod.example.com/api/v1/exchange"),
		CodeQLCLIPath:       os.Getenv("CODEQL_CLI_PATH"),
		BCSEndpoint:         os.Getenv("MRVA_BCS_ENDPOINT"),
		Bucket:              os.Getenv("MRVA_BUCKET"),
		HEPCEndpoint:        os.Getenv("MRVA_HEPC_ENDPOINT"),
		HEPCCacheDuration:   os.Getenv("MRVA_HEPC_CACHE_DURATION"),
		HEPCDataViaCLI:      os.Getenv("MRVA_HEPC_DATAVIACLI"),
		HEPCOutDir:          os.Getenv("MRVA_HEPC_OUTDIR"),
		HEPCTool:            os.Getenv("MRVA_HEPC_TOOL"),
		PostgresUser:        os.Getenv("POSTGRES_USER"),
		PostgresPassword:    os.Getenv("POSTGRES_PASSWORD"),
		PostgresHost:        os.Getenv("POSTGRES_HOST"),
		PostgresPort:        os.Getenv("POSTGRES_PORT"),
		PostgresDB:          os.Getenv("POSTGRES_DB"),
		PostgresCACert:      readCACert(),
		CodeQLRAMMB:         os.Getenv("MRVA_CODEQL_RAM_MB"),
		CodeQLThreads:       os.Getenv("MRVA_CODEQL_THREADS"),
		ADPRDUser:           os.Getenv("MRVA_ADPRD_USER"),
		ADPRDPassword:       os.Getenv("MRVA_ADPRD_PASSWORD"),
	}

	return NewArgoClient(config)
}

// NewArgoClient creates a new ArgoClient with the given configuration
func NewArgoClient(config ArgoClientConfig) (*ArgoClient, error) {
	if config.ADPRDUser == "" || config.ADPRDPassword == "" {
		slog.Error("MRVA_ADPRD_USER and MRVA_ADPRD_PASSWORD must be set")
		return nil, fmt.Errorf("MRVA_ADPRD_USER and MRVA_ADPRD_PASSWORD must be set")
	}

	// Set up HTTP client with proxy
	proxyURL, err := url.Parse(config.ProxyURL)
	if err != nil {
		slog.Error("Invalid proxy URL", "error", err, "proxy_url", config.ProxyURL)
		return nil, fmt.Errorf("invalid proxy URL: %w", err)
	}

	httpClient := &http.Client{
		Transport: &http.Transport{
			Proxy: http.ProxyURL(proxyURL),
		},
		Timeout: 30 * time.Second,
	}

	client := &ArgoClient{
		tier:                config.Tier,
		namespace:           config.Namespace,
		argoAPIBaseURL:      config.ArgoAPIBaseURL,
		proxyURL:            config.ProxyURL,
		identityExchangeURL: config.IdentityExchangeURL,
		codeqlCLIPath:       config.CodeQLCLIPath,
		bcsEndpoint:         config.BCSEndpoint,
		bucket:              config.Bucket,
		hepcEndpoint:        config.HEPCEndpoint,
		hepcCacheDuration:   config.HEPCCacheDuration,
		hepcDataViaCLI:      config.HEPCDataViaCLI,
		hepcOutDir:          config.HEPCOutDir,
		hepcTool:            config.HEPCTool,
		postgresUser:        config.PostgresUser,
		postgresPassword:    config.PostgresPassword,
		postgresHost:        config.PostgresHost,
		postgresPort:        config.PostgresPort,
		postgresDB:          config.PostgresDB,
		postgresCACert:      config.PostgresCACert,
		codeqlRAMMB:         config.CodeQLRAMMB,
		codeqlThreads:       config.CodeQLThreads,
		httpClient:          httpClient,
		adprdUser:           config.ADPRDUser,
		adprdPassword:       config.ADPRDPassword,
	}

	slog.Info("Argo client initialized",
		"tier", client.tier,
		"namespace", client.namespace)

	return client, nil
}

// identityExchangeRequest represents the request to the identity exchange service
type identityExchangeRequest struct {
	InputTokenType  string `json:"input_token_type"`
	InputToken      string `json:"input_token"`
	OutputTokenType string `json:"output_token_type"`
}

// identityExchangeResponse represents the response from the identity exchange service
type identityExchangeResponse struct {
	Expiry          string `json:"expiry"`
	OutputTokenType string `json:"output_token_type"`
	Token           string `json:"token"`
}

// getToken retrieves a valid token, refreshing if necessary
func (c *ArgoClient) getToken() (string, error) {
	// Check if we have a valid token
	c.tokenMutex.RLock()
	if c.currentToken != "" && time.Now().Before(c.tokenExpiry.Add(-5*time.Minute)) {
		token := c.currentToken
		c.tokenMutex.RUnlock()
		return token, nil
	}
	c.tokenMutex.RUnlock()

	// Need to refresh token
	c.tokenMutex.Lock()
	defer c.tokenMutex.Unlock()

	// Double-check after acquiring write lock
	if c.currentToken != "" && time.Now().Before(c.tokenExpiry.Add(-5*time.Minute)) {
		return c.currentToken, nil
	}

	slog.Info("Requesting new token from identity exchange service")

	// Prepare request
	reqBody := identityExchangeRequest{
		InputTokenType:  "urn:example:ldap:adprd",
		InputToken:      fmt.Sprintf("%s:%s", c.adprdUser, c.adprdPassword),
		OutputTokenType: "urn:example:archer:dna-sre",
	}

	reqJSON, err := json.Marshal(reqBody)
	if err != nil {
		slog.Error("Failed to marshal identity exchange request", "error", err)
		return "", fmt.Errorf("failed to marshal identity exchange request: %w", err)
	}

	req, err := http.NewRequest("POST", c.identityExchangeURL, bytes.NewReader(reqJSON))
	if err != nil {
		slog.Error("Failed to create identity exchange request", "error", err)
		return "", fmt.Errorf("failed to create identity exchange request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")

	// Execute request
	resp, err := c.httpClient.Do(req)
	if err != nil {
		slog.Error("Failed to execute identity exchange request", "error", err)
		return "", fmt.Errorf("failed to execute identity exchange request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		bodyBytes, _ := io.ReadAll(resp.Body)
		slog.Error("Identity exchange returned non-OK status", "status_code", resp.StatusCode, "body", string(bodyBytes))
		return "", fmt.Errorf("identity exchange returned status %d: %s", resp.StatusCode, string(bodyBytes))
	}

	// Parse response
	var exchangeResp identityExchangeResponse
	if err := json.NewDecoder(resp.Body).Decode(&exchangeResp); err != nil {
		slog.Error("Failed to decode identity exchange response", "error", err)
		return "", fmt.Errorf("failed to decode identity exchange response: %w", err)
	}

	// Parse expiry time
	expiry, err := time.Parse(time.RFC3339, exchangeResp.Expiry)
	if err != nil {
		slog.Error("Failed to parse token expiry", "error", err, "expiry", exchangeResp.Expiry)
		return "", fmt.Errorf("failed to parse token expiry: %w", err)
	}

	c.currentToken = exchangeResp.Token
	c.tokenExpiry = expiry

	slog.Info("Successfully obtained new token", "expiry", expiry)

	return c.currentToken, nil
}

// getEnvOrDefault returns the value of an environment variable or a default value
func getEnvOrDefault(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

// readCACert reads the Postgres CA certificate file (if configured) and returns its content.
func readCACert() string {
	certFile := os.Getenv("POSTGRES_CA_CERT_FILE")
	if certFile == "" {
		return ""
	}
	data, err := os.ReadFile(certFile)
	if err != nil {
		slog.Error("Failed to read POSTGRES_CA_CERT_FILE", "file", certFile, "error", err)
		return ""
	}
	slog.Info("Read Postgres CA certificate", "file", certFile, "size", len(data))
	return string(data)
}

// workflowSpec represents the Argo Workflow specification
type workflowSpec struct {
	APIVersion string           `json:"apiVersion"`
	Kind       string           `json:"kind"`
	Metadata   workflowMetadata `json:"metadata"`
	Spec       workflowSpecBody `json:"spec"`
}

type workflowMetadata struct {
	GenerateName string `json:"generateName"`
}

type workflowSpecBody struct {
	Entrypoint string             `json:"entrypoint"`
	PodGC      *podGCSpec         `json:"podGC,omitempty"`
	Templates  []workflowTemplate `json:"templates"`
}

type podGCSpec struct {
	Strategy string `json:"strategy"`
}

type workflowTemplate struct {
	Name   string          `json:"name"`
	Script *scriptTemplate `json:"script,omitempty"`
}

type scriptTemplate struct {
	Image           string                `json:"image"`
	ImagePullPolicy string                `json:"imagePullPolicy,omitempty"`
	Command         []string              `json:"command"`
	Args            []string              `json:"args"`
	Env             []envVar              `json:"env"`
	Resources       *resourceRequirements `json:"resources,omitempty"`
}

type resourceRequirements struct {
	Requests map[string]string `json:"requests,omitempty"`
	Limits   map[string]string `json:"limits,omitempty"`
}

type envVar struct {
	Name      string        `json:"name"`
	Value     string        `json:"value,omitempty"`
	ValueFrom *envVarSource `json:"valueFrom,omitempty"`
}

type envVarSource struct {
	SecretKeyRef *secretKeySelector `json:"secretKeyRef,omitempty"`
}

type secretKeySelector struct {
	Name string `json:"name"`
	Key  string `json:"key"`
}

// createWorkflowSpec creates an Argo Workflow specification for the given job
func (c *ArgoClient) createWorkflowSpec(job queue.AnalyzeJob) (*workflowSpec, error) {
	// Determine secret name and generateName based on tier
	secretName := "mrva-secrets"
	generateName := fmt.Sprintf("mrva-agent-workflow-prod-%s-", job.QueryLanguage)
	if c.tier == "dev" {
		secretName = "mrva-secrets-dev"
		generateName = fmt.Sprintf("mrva-agent-workflow-dev-%s-", job.QueryLanguage)
	}

	// Build environment variables
	envVars := []envVar{
		{
			Name: "MRVA_BCS_ACCESS_KEY",
			ValueFrom: &envVarSource{
				SecretKeyRef: &secretKeySelector{
					Name: secretName,
					Key:  "MRVA_BCS_ACCESS_KEY",
				},
			},
		},
		{
			Name: "MRVA_BCS_SECRET_KEY",
			ValueFrom: &envVarSource{
				SecretKeyRef: &secretKeySelector{
					Name: secretName,
					Key:  "MRVA_BCS_SECRET_KEY",
				},
			},
		},
		{Name: "CODEQL_CLI_PATH", Value: c.codeqlCLIPath},
		{Name: "MRVA_AGENT_WORKERS", Value: "1"},
		{Name: "MRVA_BCS_ENDPOINT", Value: c.bcsEndpoint},
		{Name: "MRVA_BUCKET", Value: c.bucket},
		{Name: "MRVA_HEPC_ENDPOINT", Value: c.hepcEndpoint},
		{Name: "MRVA_HEPC_CACHE_DURATION", Value: c.hepcCacheDuration},
		{Name: "MRVA_HEPC_DATAVIACLI", Value: c.hepcDataViaCLI},
		{Name: "MRVA_HEPC_OUTDIR", Value: c.hepcOutDir},
		{Name: "MRVA_HEPC_TOOL", Value: c.hepcTool},
		{Name: "MRVA_MINIO_VIRTUAL_HOST", Value: "1"},
		{Name: "POSTGRES_USER", Value: c.postgresUser},
		{Name: "POSTGRES_PASSWORD", Value: c.postgresPassword},
		{Name: "POSTGRES_HOST", Value: c.postgresHost},
		{Name: "POSTGRES_PORT", Value: c.postgresPort},
		{Name: "POSTGRES_DB", Value: c.postgresDB},
		{Name: "POSTGRES_CA_CERT", Value: c.postgresCACert},
	}

	// Pool mode is the only execution model: the agent claims jobs from
	// PostgreSQL and persists results back to it, so no --job flag is passed.
	slog.Info("Creating pool mode workflow", "job", job.Spec)

	if c.codeqlRAMMB != "" {
		envVars = append(envVars, envVar{Name: "MRVA_CODEQL_RAM_MB", Value: c.codeqlRAMMB})
	}

	if c.codeqlThreads != "" {
		envVars = append(envVars, envVar{Name: "MRVA_CODEQL_THREADS", Value: c.codeqlThreads})
	}

	spec := &workflowSpec{
		APIVersion: "argoproj.io/v1alpha1",
		Kind:       "Workflow",
		Metadata: workflowMetadata{
			GenerateName: generateName,
		},
		Spec: workflowSpecBody{
			Entrypoint: "main",
			PodGC: &podGCSpec{
				Strategy: "OnPodCompletion",
			},
			Templates: []workflowTemplate{
				{
					Name: "main",
					Script: &scriptTemplate{
						Image:           getEnvOrDefault("MRVA_ARGO_IMAGE", "artifactory.inf.example.com/wflo-devise-prod/agent-commander-argo:cce7216-97793330"),
						ImagePullPolicy: "IfNotPresent",
						Command:         []string{"/layers/paketo-buildpacks_go-build/targets/bin/mrvaagent"},
						Args:            []string{},
						Env:             envVars,
						Resources: &resourceRequirements{
							Requests: map[string]string{
								"cpu":    "4",
								"memory": "16Gi",
							},
							Limits: map[string]string{
								"cpu":    "4",
								"memory": "16Gi",
							},
						},
					},
				},
			},
		},
	}

	return spec, nil
}

// workflowSubmitRequest represents the request to submit a workflow
type workflowSubmitRequest struct {
	Spec workflowSpec `json:"spec"`
}

// workflowSubmitResponse represents the response from submitting a workflow
type workflowSubmitResponse struct {
	Workflow struct {
		Metadata workflowResponseMetadata `json:"metadata"`
		Spec     interface{}              `json:"spec"`
		Status   interface{}              `json:"status,omitempty"`
	} `json:"workflow"`
}

type workflowResponseMetadata struct {
	Name        string            `json:"name"`
	Namespace   string            `json:"namespace"`
	UID         string            `json:"uid"`
	Annotations map[string]string `json:"annotations"`
}

// WorkflowMetadata holds the essential information needed to track and query an Argo workflow
type WorkflowMetadata struct {
	Name    string `json:"name"`
	UID     string `json:"uid"`
	Cluster string `json:"cluster"`
}

// SubmitWorkflow submits a workflow to Argo and returns its UID
func (c *ArgoClient) SubmitWorkflow(job queue.AnalyzeJob) (string, error) {
	slog.Info("Submitting workflow to Argo",
		"session_id", job.Spec.SessionID,
		"owner", job.Spec.Owner,
		"repo", job.Spec.Repo,
		"language", job.QueryLanguage)

	// Get authentication token
	token, err := c.getToken()
	if err != nil {
		slog.Error("Failed to get authentication token for workflow submission", "error", err, "job", job.Spec)
		return "", fmt.Errorf("failed to get authentication token: %w", err)
	}

	// Create workflow spec
	workflowSpec, err := c.createWorkflowSpec(job)
	if err != nil {
		slog.Error("Failed to create workflow spec", "error", err, "job", job.Spec)
		return "", fmt.Errorf("failed to create workflow spec: %w", err)
	}

	// Prepare submission request
	submitReq := workflowSubmitRequest{
		Spec: *workflowSpec,
	}

	reqJSON, err := json.Marshal(submitReq)
	if err != nil {
		slog.Error("Failed to marshal workflow submit request", "error", err, "job", job.Spec)
		return "", fmt.Errorf("failed to marshal workflow submit request: %w", err)
	}

	// Build URL - always use 'dev' tier for Argo platform (prod workloads run in dev tier)
	workflowURL := fmt.Sprintf("%s/workflow/tiers/dev/namespaces/%s/workflows?dryRun=false&bypassApproval=true",
		c.argoAPIBaseURL, c.namespace)

	// Create HTTP request
	req, err := http.NewRequest("POST", workflowURL, bytes.NewReader(reqJSON))
	if err != nil {
		slog.Error("Failed to create workflow submit HTTP request", "error", err, "url", workflowURL)
		return "", fmt.Errorf("failed to create workflow submit request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")
	req.Header.Set("Authorization", fmt.Sprintf("Bearer %s", token))

	// Execute request
	resp, err := c.httpClient.Do(req)
	if err != nil {
		slog.Error("Failed to execute workflow submit HTTP request", "error", err, "url", workflowURL)
		return "", fmt.Errorf("failed to execute workflow submit request: %w", err)
	}
	defer resp.Body.Close()

	// Read response body
	bodyBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		slog.Error("Failed to read workflow submit response body", "error", err)
		return "", fmt.Errorf("failed to read workflow submit response: %w", err)
	}

	// Log response for debugging
	slog.Debug("Workflow submit response",
		"status_code", resp.StatusCode,
		"location", resp.Header.Get("Location"),
		"body", string(bodyBytes))

	// Check status code
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		slog.Error("Workflow submission failed", "status_code", resp.StatusCode, "body", string(bodyBytes), "job", job.Spec)
		return "", fmt.Errorf("workflow submission failed with status %d: %s", resp.StatusCode, string(bodyBytes))
	}

	// Parse response
	var submitResp workflowSubmitResponse
	if err := json.Unmarshal(bodyBytes, &submitResp); err != nil {
		slog.Error("Failed to decode workflow submit response", "error", err, "body", string(bodyBytes))
		return "", fmt.Errorf("failed to decode workflow submit response: %w", err)
	}

	workflowName := submitResp.Workflow.Metadata.Name
	workflowUID := submitResp.Workflow.Metadata.UID
	location := resp.Header.Get("Location")

	// Extract cluster from annotations
	var cluster string
	if clusterAnnotation, ok := submitResp.Workflow.Metadata.Annotations["dna.example.com/clusters"]; ok {
		// The annotation value is like "bri:si:workflow:managed-compute-cluster:wflo-argo-ob-dev05"
		// We want the last component (wflo-argo-ob-dev05)
		parts := bytes.Split([]byte(clusterAnnotation), []byte(":"))
		if len(parts) > 0 {
			cluster = string(parts[len(parts)-1])
		}
	}

	if cluster == "" {
		slog.Warn("Could not extract cluster from workflow metadata", "workflow_name", workflowName)
	}

	slog.Info("Successfully submitted workflow",
		"workflow_name", workflowName,
		"workflow_uid", workflowUID,
		"cluster", cluster,
		"location", location)

	// Create metadata struct and serialize to JSON
	metadata := WorkflowMetadata{
		Name:    workflowName,
		UID:     workflowUID,
		Cluster: cluster,
	}

	metadataJSON, err := json.Marshal(metadata)
	if err != nil {
		slog.Error("Failed to marshal workflow metadata", "error", err, "metadata", metadata)
		return "", fmt.Errorf("failed to marshal workflow metadata: %w", err)
	}

	// Return the metadata as JSON string (for storage in database)
	return string(metadataJSON), nil
}

// workflowStatusResponse represents the response from querying workflow status
type workflowStatusResponse struct {
	Metadata workflowResponseMetadata `json:"metadata"`
	Spec     interface{}              `json:"spec"`
	Phase    string                   `json:"phase"`
}

// GetWorkflowStatus retrieves the current status of a workflow using metadata
// The input parameter should be a JSON-encoded WorkflowMetadata string
func (c *ArgoClient) GetWorkflowStatus(workflowMetadataJSON string) (string, error) {
	// Parse the workflow metadata
	var metadata WorkflowMetadata
	if err := json.Unmarshal([]byte(workflowMetadataJSON), &metadata); err != nil {
		// For backward compatibility, try treating it as a plain UID
		slog.Warn("Failed to parse workflow metadata JSON, treating as legacy UID", "error", err)
		slog.Error("Workflow metadata is not in expected format", "error", err, "metadata_json", workflowMetadataJSON)
		return "", fmt.Errorf("workflow metadata is not in expected format (needs name and cluster): %w", err)
	}

	slog.Debug("Checking workflow status",
		"workflow_name", metadata.Name,
		"workflow_uid", metadata.UID,
		"cluster", metadata.Cluster)

	if metadata.Name == "" || metadata.Cluster == "" {
		slog.Error("Workflow metadata missing required fields", "name", metadata.Name, "cluster", metadata.Cluster)
		return "", fmt.Errorf("workflow metadata missing required fields (name=%s, cluster=%s)", metadata.Name, metadata.Cluster)
	}

	// Get authentication token
	token, err := c.getToken()
	if err != nil {
		slog.Error("Failed to get authentication token for workflow status", "error", err, "workflow_name", metadata.Name)
		return "", fmt.Errorf("failed to get authentication token: %w", err)
	}

	// Build URL to query cluster directly
	// Format: https://argo.workers.<cluster>.kaas.dev.example.com/api/v1/workflows/<namespace>/<workflow-name>
	statusURL := fmt.Sprintf("https://argo.workers.%s.kaas.dev.example.com/api/v1/workflows/%s/%s",
		metadata.Cluster, c.namespace, metadata.Name)

	// Create HTTP request
	req, err := http.NewRequest("GET", statusURL, nil)
	if err != nil {
		slog.Error("Failed to create workflow status HTTP request", "error", err, "url", statusURL)
		return "", fmt.Errorf("failed to create workflow status request: %w", err)
	}

	req.Header.Set("Accept", "application/json")
	req.Header.Set("Authorization", fmt.Sprintf("Bearer %s", token))

	// Execute request
	resp, err := c.httpClient.Do(req)
	if err != nil {
		slog.Error("Failed to execute workflow status HTTP request", "error", err, "url", statusURL)
		return "", fmt.Errorf("failed to execute workflow status request: %w", err)
	}
	defer resp.Body.Close()

	// Read response body
	bodyBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		slog.Error("Failed to read workflow status response body", "error", err)
		return "", fmt.Errorf("failed to read workflow status response: %w", err)
	}

	// Check status code
	if resp.StatusCode != http.StatusOK {
		slog.Error("Workflow status check failed", "status_code", resp.StatusCode, "body", string(bodyBytes), "workflow_name", metadata.Name)
		return "", fmt.Errorf("workflow status check failed with status %d: %s", resp.StatusCode, string(bodyBytes))
	}

	// Parse response - cluster API returns status.phase
	var statusResp struct {
		Metadata struct {
			Name string `json:"name"`
			UID  string `json:"uid"`
		} `json:"metadata"`
		Status struct {
			Phase string `json:"phase"`
		} `json:"status"`
	}
	if err := json.Unmarshal(bodyBytes, &statusResp); err != nil {
		slog.Error("Failed to decode workflow status response", "error", err, "body", string(bodyBytes))
		return "", fmt.Errorf("failed to decode workflow status response: %w", err)
	}

	phase := statusResp.Status.Phase
	if phase == "" {
		phase = "Unknown"
	}

	slog.Debug("Workflow status retrieved",
		"workflow_name", metadata.Name,
		"workflow_uid", metadata.UID,
		"cluster", metadata.Cluster,
		"phase", phase)

	return phase, nil
}

// CancelWorkflow attempts to cancel a running workflow using metadata
// The input parameter should be a JSON-encoded WorkflowMetadata string
func (c *ArgoClient) CancelWorkflow(workflowMetadataJSON string) (bool, error) {
	// Parse the workflow metadata
	var metadata WorkflowMetadata
	if err := json.Unmarshal([]byte(workflowMetadataJSON), &metadata); err != nil {
		// For backward compatibility, try treating it as a plain UID
		slog.Warn("Failed to parse workflow metadata JSON, treating as legacy UID", "error", err)
		slog.Error("Workflow metadata is not in expected format for cancel", "error", err, "metadata_json", workflowMetadataJSON)
		return false, fmt.Errorf("workflow metadata is not in expected format (needs name and cluster): %w", err)
	}

	slog.Info("Cancelling workflow",
		"workflow_name", metadata.Name,
		"workflow_uid", metadata.UID,
		"cluster", metadata.Cluster)

	if metadata.Name == "" {
		slog.Error("Workflow metadata missing required name field for cancel")
		return false, fmt.Errorf("workflow metadata missing required name field")
	}

	// Get authentication token
	token, err := c.getToken()
	if err != nil {
		slog.Error("Failed to get authentication token for workflow cancel", "error", err, "workflow_name", metadata.Name)
		return false, fmt.Errorf("failed to get authentication token: %w", err)
	}

	// Terminate using the base Argo API with authorization token
	// Format: <argoAPIBaseURL>/api/v1/workflows/<namespace>/<workflow-name>/terminate
	cancelURL := fmt.Sprintf("%s/api/v1/workflows/%s/%s/terminate",
		c.argoAPIBaseURL, c.namespace, metadata.Name)

	// Create HTTP request for termination
	req, err := http.NewRequest("PUT", cancelURL, nil)
	if err != nil {
		slog.Error("Failed to create workflow cancel HTTP request", "error", err, "url", cancelURL)
		return false, fmt.Errorf("failed to create workflow cancel request: %w", err)
	}

	req.Header.Set("Accept", "application/json")
	req.Header.Set("Authorization", fmt.Sprintf("Bearer %s", token))

	// Execute request
	resp, err := c.httpClient.Do(req)
	if err != nil {
		slog.Error("Failed to execute workflow cancel HTTP request", "error", err, "url", cancelURL)
		return false, fmt.Errorf("failed to execute workflow cancel request: %w", err)
	}
	defer resp.Body.Close()

	// Read response body
	bodyBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		slog.Error("Failed to read workflow cancel response body", "error", err)
		return false, fmt.Errorf("failed to read workflow cancel response: %w", err)
	}

	// Check status code (terminate returns 204 No Content on success)
	if resp.StatusCode == http.StatusNoContent {
		slog.Info("Successfully terminated workflow",
			"workflow_name", metadata.Name,
			"workflow_uid", metadata.UID)
		return true, nil
	}

	if resp.StatusCode == http.StatusNotFound {
		slog.Info("Workflow already completed or not found",
			"workflow_name", metadata.Name,
			"workflow_uid", metadata.UID)
		return true, nil
	}

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		slog.Error("Workflow termination failed", "status_code", resp.StatusCode, "body", string(bodyBytes), "workflow_name", metadata.Name)
		return false, fmt.Errorf("workflow termination failed with status %d: %s", resp.StatusCode, string(bodyBytes))
	}

	slog.Info("Successfully terminated workflow",
		"workflow_name", metadata.Name,
		"workflow_uid", metadata.UID)
	return true, nil
}
