package agentruntime

// NewFailure exposes a normalized installation dependency/capability reason,
// never an underlying URL, credential or raw database/transport error.
func NewFailure(status int, code string) error {
	if status < 400 || status > 599 || len(code) == 0 || len(code) > 128 {
		return ErrUnavailable
	}
	return arFailure(status, code)
}
