package server

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/hohn/mrvacommander/pkg/state"
)

type submissionState struct {
	state.ServerState
}

func (submissionState) NextID() int { return 1 }

func TestSubmissionReadsExpectContinueBeforeResponding(t *testing.T) {
	commander := &CommanderSingle{v: &Visibles{State: submissionState{}}}
	server := httptest.NewServer(http.HandlerFunc(commander.MRVARequestCommon))
	defer server.Close()

	request, err := http.NewRequest(http.MethodPost, server.URL,
		bytes.NewReader(bytes.Repeat([]byte("invalid JSON"), 200000)))
	if err != nil {
		t.Fatal(err)
	}
	request.Header.Set("Expect", "100-continue")
	client := server.Client()
	client.Timeout = 5 * time.Second
	response, err := client.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", response.StatusCode)
	}
	body, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(body), "invalid character") {
		t.Fatalf("unexpected error response: %s", body)
	}
}

type failedSubmissionBody struct{}

func (failedSubmissionBody) Read([]byte) (int, error) {
	return 0, errors.New("submission body unavailable")
}
func (failedSubmissionBody) Close() error { return nil }

func TestSubmissionReadFailureReturnsBadRequest(t *testing.T) {
	commander := &CommanderSingle{v: &Visibles{State: submissionState{}}}
	request := httptest.NewRequest(http.MethodPost, "/", nil)
	request.Body = failedSubmissionBody{}
	response := httptest.NewRecorder()
	commander.MRVARequestCommon(response, request)
	if response.Code != http.StatusBadRequest ||
		!strings.Contains(response.Body.String(), "submission body unavailable") {
		t.Fatalf("unexpected response: %d %s", response.Code, response.Body.String())
	}
}

func TestSubmissionInvalidRepositoryReturnsBadRequest(t *testing.T) {
	for _, repository := range []string{"missing-owner", "/repo", "owner/"} {
		t.Run(repository, func(t *testing.T) {
			commander := &CommanderSingle{v: &Visibles{State: submissionState{}}}
			body := fmt.Sprintf(`{"repositories":[%q]}`, repository)
			request := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(body))
			response := httptest.NewRecorder()
			commander.MRVARequestCommon(response, request)
			if response.Code != http.StatusBadRequest ||
				!strings.Contains(response.Body.String(), "invalid owner/repository") {
				t.Fatalf("unexpected response: %d %s", response.Code, response.Body.String())
			}
		})
	}
}
