package kernel

import (
	"crypto/tls"
	"crypto/x509"
	"io"
	"net"
	"net/http"
	"os"
	"time"
)

// RelayTLSFiles is installation input, never request/profile/provider input.
// Opening a relay does not approve a profile, install H1-H4 or expose a listener.
type RelayTLSFiles struct {
	Endpoint, CAFile, CertificateFile, KeyFile string
	DialTimeout, HeaderTimeout                 time.Duration
	MaxBytes                                   int64
	MaxLine                                    int
}

func readRelayPEM(name string) ([]byte, error) {
	if name == "" {
		return nil, ErrUnavailable
	}
	f, e := os.Open(name)
	if e != nil {
		return nil, ErrUnavailable
	}
	defer f.Close()
	b, e := io.ReadAll(io.LimitReader(f, 65537))
	if e != nil || len(b) == 0 || len(b) > 65536 {
		return nil, ErrUnavailable
	}
	return b, nil
}

// OpenRelayTLS constructs the existing sole relay with a dedicated trust bundle
// and client certificate. Environment proxies, redirects and cross-source
// fallback are absent. File/PEM errors never disclose paths or key bytes.
func OpenRelayTLS(core *Store, config RelayTLSFiles) (*Relay, error) {
	if config.DialTimeout <= 0 || config.DialTimeout > time.Minute || config.HeaderTimeout <= 0 || config.HeaderTimeout > time.Minute {
		return nil, ErrUnavailable
	}
	ca, e := readRelayPEM(config.CAFile)
	if e != nil {
		return nil, e
	}
	cert, e := readRelayPEM(config.CertificateFile)
	if e != nil {
		return nil, e
	}
	key, e := readRelayPEM(config.KeyFile)
	if e != nil {
		return nil, e
	}
	defer func() {
		for i := range key {
			key[i] = 0
		}
	}()
	roots := x509.NewCertPool()
	if !roots.AppendCertsFromPEM(ca) {
		return nil, ErrUnavailable
	}
	pair, e := tls.X509KeyPair(cert, key)
	if e != nil || len(pair.Certificate) == 0 {
		return nil, ErrUnavailable
	}
	leaf, e := x509.ParseCertificate(pair.Certificate[0])
	now := time.Now()
	if e != nil || now.Before(leaf.NotBefore) || !now.Before(leaf.NotAfter) {
		return nil, ErrUnavailable
	}
	transport := &http.Transport{
		Proxy:               nil,
		DialContext:         (&net.Dialer{Timeout: config.DialTimeout, KeepAlive: 30 * time.Second}).DialContext,
		TLSClientConfig:     &tls.Config{MinVersion: tls.VersionTLS12, RootCAs: roots, Certificates: []tls.Certificate{pair}},
		TLSHandshakeTimeout: config.DialTimeout, ResponseHeaderTimeout: config.HeaderTimeout,
		MaxResponseHeaderBytes: 16384, MaxIdleConns: 16, MaxIdleConnsPerHost: 4, IdleConnTimeout: 30 * time.Second,
		DisableCompression: true,
	}
	relay, e := NewRelay(core, config.Endpoint, transport, config.MaxBytes, config.MaxLine)
	if e != nil {
		return nil, ErrUnavailable
	}
	return relay, nil
}

// Close releases idle TLS connections; in-flight requests retain their original
// context/deadline and unique settlement ownership.
func (r *Relay) Close() { r.client.CloseIdleConnections() }
