package publisher

import (
	"context"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"github.com/jianzi123/maas/internal/release"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"
)

// Start the actual binary against the owned MySQL and collect its exact child.
func checkPublisherProcess(t *testing.T, config Config, transport *http.Transport, serverCertificate [][]byte, serverPrivateKey any, command release.Command) {
	t.Helper()
	binary := os.Getenv("MAAS_PUBLISHER_TEST_BINARY")
	if binary == "" {
		t.Fatal("owned test requires the cross-built publisher binary")
	}
	dir := t.TempDir()
	write := func(name string, b []byte) string {
		t.Helper()
		path := filepath.Join(dir, name)
		if e := os.WriteFile(path, b, 0600); e != nil {
			t.Fatal(e)
		}
		return path
	}
	key, e := x509.MarshalPKCS8PrivateKey(serverPrivateKey)
	if e != nil {
		t.Fatal(e)
	}
	config.ServerKey = write("server.key", pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: key}))
	config.ServerCertificate = write("server.crt", pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: serverCertificate[0]}))
	config.ClientCA = write("operator-ca.crt", pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: serverCertificate[1]}))
	config.OperatorIdentity = operatorID
	port, e := net.Listen("tcp", "127.0.0.1:0")
	if e != nil {
		t.Fatal(e)
	}
	config.Listen = port.Addr().String()
	_ = port.Close()
	b, _ := json.Marshal(config)
	configPath := write("publisher.json", b)
	process := exec.Command(binary, "-config", configPath)
	process.Stdout = io.Discard
	process.Stderr = io.Discard
	if e = process.Start(); e != nil {
		t.Fatal(e)
	}
	exited := make(chan error, 1)
	go func() { exited <- process.Wait() }()
	t.Cleanup(func() {
		_ = process.Process.Signal(os.Interrupt)
		select {
		case exitErr := <-exited:
			if exitErr != nil {
				t.Errorf("publisher shutdown failed: %v", exitErr)
			}
		case <-time.After(6 * time.Second):
			_ = process.Process.Kill()
			<-exited
			t.Error("publisher graceful shutdown exceeded bound")
		}
	})
	client := &http.Client{Transport: transport, Timeout: time.Second}
	deadline := time.Now().Add(time.Second * 5)
	healthy := false
	for time.Now().Before(deadline) {
		response, e := client.Get("https://" + config.Listen + "/healthz")
		if e == nil {
			_ = response.Body.Close()
			if response.StatusCode == 204 {
				healthy = true
				break
			}
		}
		time.Sleep(20 * time.Millisecond)
	}
	if !healthy {
		t.Fatal("publisher process did not become live")
	}
	response, e := client.Get("https://" + config.Listen + "/readyz")
	if e != nil {
		t.Fatal(e)
	}
	body, _ := io.ReadAll(response.Body)
	_ = response.Body.Close()
	if response.StatusCode != 503 || string(body) != "DependencyMissing\n" {
		t.Fatal("process invented readiness", response.StatusCode)
	}
	caller, e := release.NewCommandClient("https://"+config.Listen, transport.TLSClientConfig)
	if e != nil {
		t.Fatal(e)
	}
	if e = caller.Send(context.Background(), command); e != nil {
		t.Fatal(e)
	}
	t.Log("actual cmd/publisher: mTLS liveness 204, readiness 503, original command confirmed; shutdown collected")
}
