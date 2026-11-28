package publisher

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"errors"
	"io"
	"net"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/go-sql-driver/mysql"
	"github.com/jianzi123/maas/internal/kernel"
	"github.com/jianzi123/maas/internal/protocol"
	"github.com/jianzi123/maas/internal/release/mysqlstore"
)

var ErrConfiguration = errors.New("publisher configuration unavailable")

type Config struct {
	Listen            string `json:"listen"`
	Cluster           string `json:"cluster_id"`
	DSNFile           string `json:"publisher_dsn_file"`
	ServerCertificate string `json:"server_certificate_file"`
	ServerKey         string `json:"server_key_file"`
	ClientCA          string `json:"operator_client_ca_file"`
	OperatorIdentity  string `json:"operator_identity"`
}

func readBounded(path string, max int64) ([]byte, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, ErrConfiguration
	}
	defer f.Close()
	b, err := io.ReadAll(io.LimitReader(f, max+1))
	if err != nil || int64(len(b)) > max || len(b) == 0 {
		return nil, ErrConfiguration
	}
	return b, nil
}
func Load(path string) (Config, error) {
	var c Config
	b, err := readBounded(path, 16384)
	if err != nil {
		return c, err
	}
	canonical, err := protocol.Canonical(b)
	if err != nil {
		return c, ErrConfiguration
	}
	d := json.NewDecoder(bytes.NewReader(canonical))
	d.DisallowUnknownFields()
	if d.Decode(&c) != nil {
		return Config{}, ErrConfiguration
	}
	host, port, err := net.SplitHostPort(c.Listen)
	if err != nil || host == "" || port == "" || !validIdentity(c.OperatorIdentity) {
		return Config{}, ErrConfiguration
	}
	if _, err = kernel.NewPublisherKernel(c.Cluster); err != nil {
		return Config{}, ErrConfiguration
	}
	for _, field := range []*string{&c.DSNFile, &c.ServerCertificate, &c.ServerKey, &c.ClientCA} {
		if *field == "" {
			return Config{}, ErrConfiguration
		}
		if !filepath.IsAbs(*field) {
			*field = filepath.Join(filepath.Dir(path), *field)
		}
	}
	return c, nil
}
func (c Config) TLS() (*tls.Config, error) {
	certificate, err := tls.LoadX509KeyPair(c.ServerCertificate, c.ServerKey)
	if err != nil {
		return nil, ErrConfiguration
	}
	b, err := readBounded(c.ClientCA, 1<<20)
	if err != nil {
		return nil, err
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(b) {
		return nil, ErrConfiguration
	}
	return &tls.Config{MinVersion: tls.VersionTLS13, ClientAuth: tls.RequireAndVerifyClientCert, ClientCAs: pool, Certificates: []tls.Certificate{certificate}}, nil
}

// Open consumes the publisher identity only. Core metadata is read using the
// existing publisher grants in that SAME transaction. No core DSN/pepper,
// migration, provisioning or proof fixture is introduced.
func (c Config) Open(ctx context.Context) (*mysqlstore.PublisherRuntime, error) {
	b, err := readBounded(c.DSNFile, 16384)
	if err != nil {
		return nil, err
	}
	defer func() {
		for i := range b {
			b[i] = 0
		}
	}()
	dsn := strings.TrimSpace(string(b))
	cfg, err := mysql.ParseDSN(dsn)
	if err != nil || cfg.Net != "unix" && cfg.Net != "tcp" || !cfg.ParseTime || cfg.Loc != time.UTC || cfg.Params["time_zone"] != "'+00:00'" || cfg.MultiStatements || cfg.Timeout <= 0 || cfg.ReadTimeout <= 0 || cfg.WriteTimeout <= 0 {
		return nil, ErrConfiguration
	}
	if cfg.Net == "tcp" && (cfg.TLSConfig == "" || cfg.TLSConfig == "false" || cfg.TLSConfig == "skip-verify" || cfg.TLSConfig == "preferred") {
		return nil, ErrConfiguration
	}
	k, err := kernel.NewPublisherKernel(c.Cluster)
	if err != nil {
		return nil, ErrConfiguration
	}
	runtime, err := mysqlstore.OpenPublisher(ctx, dsn, c.Cluster, k)
	if err != nil {
		return nil, ErrConfiguration
	}
	return runtime, nil
}
