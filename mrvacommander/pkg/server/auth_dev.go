package server

import (
	"log/slog"
	"net/http"
)

// DevUserHeader is the request header the standalone/dev authenticator
// reads the username from. Test and dev clients set it per request so a
// single local server can attribute jobs to different users (e.g. alice
// and bob) without a real identity provider.
const DevUserHeader = "X-MRVA-User"

// devAuthenticator resolves the username from the DevUserHeader request
// header. It performs NO verification and MUST NOT be used in production;
// it exists only for --mode=standalone local development and testing,
// where there is no JWKS/JWT infrastructure.
type devAuthenticator struct{}

// NewDevAuthenticator returns the standalone/dev Authenticator, which
// trusts the DevUserHeader value verbatim.
func NewDevAuthenticator() Authenticator { return devAuthenticator{} }

func (devAuthenticator) Authenticate(r *http.Request) (string, error) {
	user := r.Header.Get(DevUserHeader)
	if user == "" {
		return "", ErrNoCredentials
	}
	slog.Info("Dev-authenticated user", "user", user, "method", r.Method, "uri", r.RequestURI)
	return user, nil
}
