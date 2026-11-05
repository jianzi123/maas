package release

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"

	"github.com/google/uuid"
)

// CommandClient sends the approved command endpoint only. It deliberately does
// not claim to implement the missing durable observation/inventory/receipt ports.
type CommandClient struct {
	client *http.Client
	base   string
}

func NewCommandClient(base string, t *tls.Config) (*CommandClient, error) {
	u, err := url.Parse(base)
	if err != nil || u.Scheme != "https" || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || (u.Path != "" && u.Path != "/") || t == nil || t.InsecureSkipVerify || (len(t.Certificates) == 0 && t.GetClientCertificate == nil) || t.RootCAs == nil {
		return nil, ErrDependencyMissing
	}
	cfg := t.Clone()
	if cfg.MinVersion < tls.VersionTLS12 {
		cfg.MinVersion = tls.VersionTLS12
	}
	return &CommandClient{base: strings.TrimRight(base, "/"), client: &http.Client{Transport: &http.Transport{TLSClientConfig: cfg}, Timeout: 15 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}}, nil
}
func (c *CommandClient) Send(ctx context.Context, cmd Command) error {
	if err := ValidateCommand(cmd); err != nil {
		return err
	}
	data, err := json.Marshal(cmd)
	if err != nil {
		return ErrConflict
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.base+"/internal/v1/releases/"+cmd.CRUID+"/commands", bytes.NewReader(data))
	if err != nil {
		return ErrDependencyMissing
	}
	req.Header.Set("Content-Type", "application/json")
	// No automatic application retry: a timeout can mean a committed command.
	// Caller recovers its durable state using the unchanged command ID.
	res, err := c.client.Do(req)
	if err != nil {
		return ErrDependencyMissing
	}
	defer res.Body.Close()
	_, _ = io.Copy(io.Discard, io.LimitReader(res.Body, 4096))
	if res.StatusCode == http.StatusConflict {
		return ErrConflict
	}
	if res.StatusCode != http.StatusOK && res.StatusCode != http.StatusAccepted && res.StatusCode != http.StatusNoContent {
		return errors.New("release control unavailable")
	}
	return nil
}

var revisionPattern = regexp.MustCompile(`^[0-9a-f]{64}$`)

func ValidateCommand(c Command) error {
	validID := func(s string) bool { v, err := uuid.Parse(s); return err == nil && v.String() == s }
	if !validID(c.ID) || !validID(c.CRUID) || c.Generation < 1 || c.Generation > 9007199254740991 || c.Fence < 1 || c.Fence > 9007199254740991 || !revisionPattern.MatchString(c.Revision) || c.EvidenceRefs == nil || len(c.EvidenceRefs) > 32 {
		return ErrConflict
	}
	for _, p := range []*string{c.ExpectedActive, c.Target} {
		if p != nil && !validID(*p) {
			return ErrConflict
		}
	}
	for _, ref := range c.EvidenceRefs {
		if !validID(ref) {
			return ErrConflict
		}
	}
	switch c.Action {
	case "Prepare", "CloseAdmission", "RecordCleanup":
	case "Activate", "RequestValidation", "RecordGatewayReceipt", "RetireRuntime":
		if c.Target == nil {
			return ErrConflict
		}
	default:
		return ErrConflict
	}
	return nil
}
