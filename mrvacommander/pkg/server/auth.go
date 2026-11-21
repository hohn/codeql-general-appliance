package server

import (
	"context"
	"crypto/rsa"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"math/big"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/gorilla/mux"
)

const (
	expectedAudience = "psa-mrva"
	expectedIssuer   = "https://auth.dx.example.com:4430/"
	expectedJKU      = "https://auth.dx.example.com:4430/.well-known/jwks.json"
	jwksURL          = "https://auth.dx.example.com:4430/.well-known/jwks.json"
)

type contextKey string

const userContextKey contextKey = "mrva-user"

var (
	requireJWTAuth bool = false
)

func init() {
	val := os.Getenv("MRVA_REQUIRE_JWT_AUTH")
	if val != "" {
		requireJWTAuth = true
	}
}

// ErrNoCredentials signals that a request carried no authentication
// material at all (e.g. no Authorization header for the JWT authenticator,
// or no user header for the dev authenticator). The middleware treats this
// specially: when requireJWTAuth is false the request proceeds as the
// anonymous "UNKNOWN" user; when true it is rejected with 401. Any other
// error from Authenticate means credentials were present but invalid and
// always yields a 401.
var ErrNoCredentials = errors.New("no credentials presented")

// Authenticator extracts the authenticated username from an incoming
// request. Implementations are selected by --mode (mirroring how
// state.ServerState is chosen): the production JWT validator in container
// mode, the request-header shim in standalone mode.
type Authenticator interface {
	Authenticate(r *http.Request) (user string, err error)
}

type JWKS struct {
	Keys []JSONWebKey `json:"keys"`
}

type JSONWebKey struct {
	Kty string `json:"kty"`
	Kid string `json:"kid"`
	Use string `json:"use"`
	N   string `json:"n"`
	E   string `json:"e"`
	Alg string `json:"alg"`
}

type JWKSCache struct {
	jwks      *JWKS
	expiresAt time.Time
	mu        sync.RWMutex
}

var globalJWKSCache = &JWKSCache{}

func (c *JWKSCache) GetKey(kid string) (*rsa.PublicKey, error) {
	c.mu.RLock()
	if c.jwks != nil && time.Now().Before(c.expiresAt) {
		key, err := c.findKey(kid)
		c.mu.RUnlock()
		if err == nil {
			return key, nil
		}
	} else {
		c.mu.RUnlock()
	}

	c.mu.Lock()
	defer c.mu.Unlock()

	if c.jwks != nil && time.Now().Before(c.expiresAt) {
		return c.findKey(kid)
	}

	slog.Info("Fetching JWKS", "url", jwksURL)
	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Get(jwksURL)
	if err != nil {
		return nil, fmt.Errorf("failed to fetch JWKS: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("failed to fetch JWKS: status %d", resp.StatusCode)
	}

	var jwks JWKS
	if err := json.NewDecoder(resp.Body).Decode(&jwks); err != nil {
		return nil, fmt.Errorf("failed to decode JWKS: %w", err)
	}

	c.jwks = &jwks
	c.expiresAt = time.Now().Add(1 * time.Hour)

	return c.findKey(kid)
}

func (c *JWKSCache) findKey(kid string) (*rsa.PublicKey, error) {
	for _, key := range c.jwks.Keys {
		if key.Kid == kid {
			return key.toRSAPublicKey()
		}
	}
	return nil, fmt.Errorf("key not found: %s", kid)
}

func (k *JSONWebKey) toRSAPublicKey() (*rsa.PublicKey, error) {
	nBytes, err := base64.RawURLEncoding.DecodeString(k.N)
	if err != nil {
		return nil, err
	}
	eBytes, err := base64.RawURLEncoding.DecodeString(k.E)
	if err != nil {
		return nil, err
	}

	var e int
	for _, v := range eBytes {
		e = e<<8 | int(v)
	}

	n := new(big.Int).SetBytes(nBytes)

	return &rsa.PublicKey{
		N: n,
		E: e,
	}, nil
}

// AuthMiddleware returns gorilla/mux middleware that resolves the request's
// username via the given Authenticator, applies the requireJWTAuth policy,
// and stashes the result in the request context for UserFromContext.
func AuthMiddleware(auth Authenticator) mux.MiddlewareFunc {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			user, err := auth.Authenticate(r)
			if err != nil {
				if errors.Is(err, ErrNoCredentials) {
					if requireJWTAuth {
						slog.Warn("Missing credentials", "method", r.Method, "uri", r.RequestURI)
						http.Error(w, "Missing Authorization header", http.StatusUnauthorized)
						return
					}
					user = "UNKNOWN"
				} else {
					slog.Error("Authentication failed", "error", err, "method", r.Method, "uri", r.RequestURI)
					http.Error(w, "Invalid token", http.StatusUnauthorized)
					return
				}
			}

			ctx := context.WithValue(r.Context(), userContextKey, user)
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

// jwtAuthenticator validates an issuer-signed RS256 JWT from the
// Authorization: Bearer header and returns its subject claim as the
// username. This is the production authenticator (container/cluster mode).
type jwtAuthenticator struct{}

// NewJWTAuthenticator returns the production JWT-validating Authenticator.
func NewJWTAuthenticator() Authenticator { return jwtAuthenticator{} }

func (jwtAuthenticator) Authenticate(r *http.Request) (string, error) {
	authHeader := r.Header.Get("Authorization")
	if authHeader == "" {
		return "", ErrNoCredentials
	}

	parts := strings.Split(authHeader, " ")
	if len(parts) != 2 || parts[0] != "Bearer" {
		return "", fmt.Errorf("invalid Authorization header format")
	}
	tokenString := parts[1]

	token, err := jwt.Parse(tokenString, func(token *jwt.Token) (interface{}, error) {
		if _, ok := token.Method.(*jwt.SigningMethodRSA); !ok {
			return nil, fmt.Errorf("unexpected signing method: %v", token.Header["alg"])
		}
		if token.Header["alg"] != "RS256" {
			return nil, fmt.Errorf("unexpected signing method: %v", token.Header["alg"])
		}

		jku, ok := token.Header["jku"].(string)
		if !ok || jku != expectedJKU {
			return nil, fmt.Errorf("invalid or missing jku header: got %q, expected %q", jku, expectedJKU)
		}

		kid, ok := token.Header["kid"].(string)
		if !ok {
			return nil, fmt.Errorf("missing kid header")
		}

		return globalJWKSCache.GetKey(kid)
	})

	if err != nil {
		return "", fmt.Errorf("JWT validation failed: %w", err)
	}
	if !token.Valid {
		return "", fmt.Errorf("token is invalid")
	}

	claims, ok := token.Claims.(jwt.MapClaims)
	if !ok {
		return "", fmt.Errorf("invalid token claims type")
	}

	if _, ok := claims["exp"]; !ok {
		return "", fmt.Errorf("token missing expiration")
	}

	aud, err := claims.GetAudience()
	if err != nil {
		return "", fmt.Errorf("invalid audience: %w", err)
	}
	audFound := false
	for _, a := range aud {
		if a == expectedAudience {
			audFound = true
			break
		}
	}
	if !audFound {
		return "", fmt.Errorf("invalid audience: got %v, expected %q", aud, expectedAudience)
	}

	iss, err := claims.GetIssuer()
	if err != nil || iss != expectedIssuer {
		return "", fmt.Errorf("invalid issuer: got %q, expected %q: %w", iss, expectedIssuer, err)
	}

	sub, err := claims.GetSubject()
	if err != nil {
		return "", fmt.Errorf("invalid subject: %w", err)
	}

	slog.Info("Authenticated user", "user", sub, "method", r.Method, "uri", r.RequestURI)
	return sub, nil
}

func UserFromContext(ctx context.Context) (string, bool) {
	user, ok := ctx.Value(userContextKey).(string)
	return user, ok
}
