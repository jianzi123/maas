package app

import (
	"context"
	"database/sql"
	"errors"
)

type physicalObject struct{ Name, Kind string }
type physicalUniqueIndex struct {
	Table, Name string
	Columns     []string
}
type physicalIndexPart struct {
	column   sql.NullString
	prefix   sql.NullInt64
	unique   bool
	sequence int
}

var errPhysicalSchema = errors.New("required_physical_schema_not_ready")

// Metadata only: never read private history rows or fall back to a management
// DSN. Missing visibility, object or integrity constraint is unavailable.
func validatePhysicalSchema(ctx context.Context, db *sql.DB) error {
	rows, e := db.QueryContext(ctx, "SELECT TABLE_NAME,TABLE_TYPE,ENGINE FROM information_schema.tables WHERE table_schema=DATABASE()")
	if e != nil {
		return errPhysicalSchema
	}
	objects := map[string]struct {
		kind   string
		engine sql.NullString
	}{}
	for rows.Next() {
		var name, kind string
		var engine sql.NullString
		if rows.Scan(&name, &kind, &engine) != nil {
			rows.Close()
			return errPhysicalSchema
		}
		objects[name] = struct {
			kind   string
			engine sql.NullString
		}{kind, engine}
	}
	e = rows.Err()
	rows.Close()
	if e != nil {
		return errPhysicalSchema
	}
	for _, required := range requiredPhysicalObjects {
		actual, ok := objects[required.Name]
		if !ok || actual.kind != required.Kind || (required.Kind == "BASE TABLE" && (!actual.engine.Valid || actual.engine.String != "InnoDB")) {
			return errPhysicalSchema
		}
	}
	rows, e = db.QueryContext(ctx, "SELECT TABLE_NAME,INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME,SUB_PART FROM information_schema.statistics WHERE table_schema=DATABASE() ORDER BY TABLE_NAME,INDEX_NAME,SEQ_IN_INDEX")
	if e != nil {
		return errPhysicalSchema
	}
	indexes := map[[2]string][]physicalIndexPart{}
	for rows.Next() {
		var table, name string
		var nonUnique int
		var part physicalIndexPart
		if rows.Scan(&table, &name, &nonUnique, &part.sequence, &part.column, &part.prefix) != nil {
			rows.Close()
			return errPhysicalSchema
		}
		part.unique = nonUnique == 0
		key := [2]string{table, name}
		indexes[key] = append(indexes[key], part)
	}
	e = rows.Err()
	rows.Close()
	if e != nil {
		return errPhysicalSchema
	}
	for _, required := range requiredUniqueIndexes {
		actual := indexes[[2]string{required.Table, required.Name}]
		if len(actual) != len(required.Columns) {
			return errPhysicalSchema
		}
		for i, column := range required.Columns {
			part := actual[i]
			if !part.unique || part.sequence != i+1 || !part.column.Valid || part.column.String != column || part.prefix.Valid {
				return errPhysicalSchema
			}
		}
	}
	var identities int
	if e = db.QueryRowContext(ctx, "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='usage_events' AND column_name IN ('request_id','event_type') AND is_nullable='NO'").Scan(&identities); e != nil || identities != 2 {
		return errPhysicalSchema
	}
	return nil
}
