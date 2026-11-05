package main

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestHealthSemantics(t *testing.T) {
	for _, status := range []int{200, 204, 302, 401, 503} {
		s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(status)
			w.Write([]byte("sensitive response must not be reported"))
		}))
		err := check(s.URL)
		s.Close()
		if (err == nil) != (status >= 200 && status < 300) {
			t.Fatalf("status %d: unexpected probe result", status)
		}
	}
}
func TestRejectUnsafeTargets(t *testing.T) {
	for _, target := range []string{
		"http://example.com/readyz", "https://127.0.0.1/readyz",
		"http://user:secret@127.0.0.1/readyz", "http://127.0.0.1/readyz?key=x",
		"http://127.0.0.1/readyz#secret",
	} {
		if check(target) == nil {
			t.Fatal("accepted unsafe target")
		}
	}
}
func TestUnavailableIsFailure(t *testing.T) {
	s := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	target := s.URL
	s.Close()
	if check(target) == nil {
		t.Fatal("closed endpoint accepted")
	}
}
func TestRedirectNotFollowed(t *testing.T) {
	calls := 0
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		http.Redirect(w, r, "/green", http.StatusFound)
	}))
	defer s.Close()
	if check(s.URL) == nil || calls != 1 {
		t.Fatal("redirect followed")
	}
}
