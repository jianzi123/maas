// Package publisher assembles the existing release store. It owns no inference
// route, credential lookup, proof producer or second admission/settlement path.
package publisher

import (
	"bytes"
	"context"
	"crypto/x509"
	"encoding/json"
	"errors"
	"io"
	"mime"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/jianzi123/maas/internal/protocol"
	"github.com/jianzi123/maas/internal/release"
	"github.com/jianzi123/maas/internal/release/mysqlstore"
)

type Commander interface {
	Apply(context.Context, release.Command) error
}
type Handler struct {
	Control          Commander
	OperatorIdentity string
}

func validIdentity(identity string) bool {
	u, err := url.Parse(identity)
	return err == nil && u.Scheme == "spiffe" && u.Host != "" && u.User == nil &&
		u.RawQuery == "" && u.Fragment == "" && u.Path != "" && u.Path != "/" && u.String() == identity
}
func (h Handler) authorized(r *http.Request) bool {
	if !validIdentity(h.OperatorIdentity) || r.TLS == nil || len(r.TLS.PeerCertificates) == 0 || len(r.TLS.VerifiedChains) == 0 {
		return false
	}
	leaf := r.TLS.PeerCertificates[0]
	now := time.Now()
	if now.Before(leaf.NotBefore) || !now.Before(leaf.NotAfter) || len(leaf.URIs) != 1 || leaf.URIs[0].String() != h.OperatorIdentity {
		return false
	}
	for _, chain := range r.TLS.VerifiedChains {
		if len(chain) > 0 && bytes.Equal(chain[0].Raw, leaf.Raw) {
			for _, usage := range leaf.ExtKeyUsage {
				if usage == x509.ExtKeyUsageClientAuth {
					return true
				}
			}
		}
	}
	return false
}
func response(w http.ResponseWriter, status int, code string) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"code": code})
}
func (h Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if !h.authorized(r) {
		response(w, http.StatusForbidden, "publisher_identity_required")
		return
	}
	if r.Method != http.MethodPost {
		response(w, http.StatusMethodNotAllowed, "method_not_allowed")
		return
	}
	const prefix = "/internal/v1/releases/"
	const suffix = "/commands"
	if r.URL.RawQuery != "" || r.URL.EscapedPath() != r.URL.Path || !strings.HasPrefix(r.URL.Path, prefix) || !strings.HasSuffix(r.URL.Path, suffix) {
		response(w, http.StatusNotFound, "not_found")
		return
	}
	uid := strings.TrimSuffix(strings.TrimPrefix(r.URL.Path, prefix), suffix)
	if strings.Contains(uid, "/") {
		response(w, http.StatusNotFound, "not_found")
		return
	}
	media, _, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
	if err != nil || media != "application/json" {
		response(w, http.StatusUnsupportedMediaType, "json_required")
		return
	}
	raw, err := io.ReadAll(io.LimitReader(r.Body, 16385))
	if err != nil || len(raw) > 16384 {
		response(w, http.StatusBadRequest, "invalid_command")
		return
	}
	canonical, err := protocol.Canonical(raw)
	if err != nil {
		response(w, http.StatusBadRequest, "invalid_command")
		return
	}
	var command release.Command
	decoder := json.NewDecoder(bytes.NewReader(canonical))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&command) != nil || release.ValidateCommand(command) != nil || command.CRUID != uid {
		response(w, http.StatusBadRequest, "invalid_command")
		return
	}
	if h.Control == nil {
		response(w, http.StatusServiceUnavailable, "DependencyMissing")
		return
	}
	err = h.Control.Apply(r.Context(), command) // never retry at the HTTP boundary
	switch {
	case err == nil:
		w.WriteHeader(http.StatusNoContent)
	case errors.Is(err, release.ErrConflict), errors.Is(err, release.ErrOwnership):
		response(w, http.StatusConflict, "release_conflict")
	case errors.Is(err, mysqlstore.ErrCommitUnknown):
		response(w, http.StatusServiceUnavailable, "release_commit_unknown")
	default:
		response(w, http.StatusServiceUnavailable, "DependencyMissing")
	}
}
