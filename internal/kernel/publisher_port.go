package kernel

import (
	"context"
	"database/sql"
	"github.com/jianzi123/maas/internal/release/mysqlstore"
	"regexp"
)

// PublisherKernel exposes same-transaction metadata/count reads only. It owns
// no core connection, Key pepper, rate gate or business-write API. The missing
// production proof adapters deliberately keep activation unavailable.
type PublisherKernel struct{ reader *Store }

func NewPublisherKernel(cluster string) (*PublisherKernel, error) {
	if !regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`).MatchString(cluster) {
		return nil, ErrUnavailable
	}
	return &PublisherKernel{reader: &Store{cluster: cluster}}, nil
}
func (p *PublisherKernel) LockCapacity(ctx context.Context, tx *sql.Tx) error {
	return p.reader.LockCapacity(ctx, tx)
}
func (p *PublisherKernel) PublicationEvidence(ctx context.Context, tx *sql.Tx, publication mysqlstore.Publication) (mysqlstore.Evidence, error) {
	return p.reader.PublicationEvidence(ctx, tx, publication)
}
func (p *PublisherKernel) DrainEvidence(ctx context.Context, tx *sql.Tx, uid string, publications []mysqlstore.Publication) (mysqlstore.DrainEvidence, error) {
	return p.reader.DrainEvidence(ctx, tx, uid, publications)
}

var _ mysqlstore.Kernel = (*PublisherKernel)(nil)
