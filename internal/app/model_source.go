package app

import (
	"context"
	"database/sql"
	"errors"

	"github.com/jianzi123/maas/internal/kernel"
	"github.com/jianzi123/maas/internal/release/mysqlstore"
)

func openModelSource(ctx context.Context, db *sql.DB, c Config, pepper []byte) (modelSource, *kernel.Store, *mysqlstore.Store, error) {
	if !c.Offline.Enabled {
		core, e := kernel.New(db, c.Cluster, pepper, nil, &kernel.DurableProofs{Cluster: c.Cluster})
		if e != nil {
			return nil, nil, nil, e
		}
		gate, e := mysqlstore.New(db, c.Cluster, core)
		if e != nil {
			return nil, nil, nil, e
		}
		m := &Models{Config: c, Core: core, Gate: gate}
		if e = m.Open(); e != nil {
			return nil, nil, nil, e
		}
		return m, core, gate, nil
	}
	state, e := loadOffline(ctx, db, c)
	if e != nil {
		return nil, nil, nil, e
	}
	key, e := offlineCrypt(pepper, state.Cipher, false)
	if e != nil {
		return nil, nil, nil, errors.New("offline_key_decryption_failed")
	}
	proofs := offlineProofs{UID: offlineUID(c.Cluster, "release"), PubID: state.Publication, Source: offlineUID(c.Cluster, "source")}
	core, e := kernel.New(db, c.Cluster, pepper, offlineRate{Key: state.KeyID}, proofs)
	if e != nil {
		return nil, nil, nil, e
	}
	gate, e := mysqlstore.New(db, c.Cluster, core)
	if e != nil {
		return nil, nil, nil, e
	}
	profile, e := core.Profile(ctx, state.Publication)
	if e != nil || profile.SourceID != proofs.Source || profile.Alias != OfflineAlias {
		return nil, nil, nil, errors.New("offline_profile_invalid")
	}
	m := &OfflineModel{Config: c, Core: core, Gate: gate, Profile: profile, State: state, Key: key}
	return m, core, gate, nil
}
