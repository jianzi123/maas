package gateway

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"github.com/jianzi123/maas/internal/protocol"
	"time"
)

// Receipt is a candidate H3 internal envelope. Its producer must inspect
// EFFECTIVE Envoy config; this verifier cannot turn CR status into that fact.
type Receipt struct {
	ID                   string `json:"receipt_id"`
	Instance             string `json:"instance_id"`
	Epoch                int64  `json:"gateway_epoch"`
	Publication          string `json:"publication_id"`
	ActivationEpoch      int64  `json:"activation_epoch"`
	RouteDigest          string `json:"route_digest"`
	ConfigDigest         string `json:"config_digest"`
	PluginDigest         string `json:"plugin_digest"`
	CredentialGeneration string `json:"credential_generation"`
	Listener             string `json:"listener"`
	ObservedMS           int64  `json:"observed_at_ms"`
	ExpiresMS            int64  `json:"expires_at_ms"`
}
type ReceiptExpectation struct {
	Receipt
	MaxAge time.Duration
}

// Key must come from a separate H3-purpose approved attestor registry. No TOFU.
func VerifyReceipt(payload []byte, signature string, key []byte, peer string, expected ReceiptExpectation, now time.Time) (Receipt, error) {
	var r Receipt
	if len(payload) > 8192 || len(key) < 32 || expected.MaxAge <= 0 {
		return r, ErrDependency
	}
	canonical, e := protocol.Canonical(payload)
	if e != nil || !bytes.Equal(canonical, payload) {
		return r, ErrDependency
	}
	sig, e := base64.RawURLEncoding.Strict().DecodeString(signature)
	if e != nil {
		return r, ErrDependency
	}
	mac := hmac.New(sha256.New, key)
	mac.Write(payload)
	if !hmac.Equal(sig, mac.Sum(nil)) {
		return r, ErrDependency
	}
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&r) != nil {
		return r, ErrDependency
	}
	want := expected.Receipt
	if r.ID == "" || r.Instance != peer || r.Instance != want.Instance || r.Epoch != want.Epoch || r.Publication != want.Publication || r.ActivationEpoch != want.ActivationEpoch || r.RouteDigest != want.RouteDigest || r.ConfigDigest != want.ConfigDigest || r.PluginDigest != want.PluginDigest || r.CredentialGeneration != want.CredentialGeneration || r.Listener != want.Listener {
		return r, ErrDependency
	}
	observed := time.UnixMilli(r.ObservedMS)
	expires := time.UnixMilli(r.ExpiresMS)
	if observed.After(now) || !now.Before(expires) || !observed.Before(expires) || now.Sub(observed) > expected.MaxAge || expires.Sub(observed) > expected.MaxAge {
		return r, ErrDependency
	}
	return r, nil
}
