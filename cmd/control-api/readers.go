package main

import (
	"context"
	"database/sql"
	"fmt"
	"time"
)

func openProjectionDB(dsn string) (*sql.DB, error) {
	if dsn == "" {
		return nil, nil
	}
	db, e := sql.Open("mysql", dsn)
	if e != nil {
		return nil, fmt.Errorf("projection reader configuration unavailable")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if db.PingContext(ctx) != nil {
		db.Close()
		return nil, fmt.Errorf("projection reader unavailable")
	}
	return db, nil
}
