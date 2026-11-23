-- C08 installation proposal only. Not applied; consumer/credentials require approval.
-- Replace __MAAS_DATABASE__ using the approved installer; never use schema.*.
-- Migration runs separately via agentruntime.Migrate; this role has no DDL/DELETE.
CREATE ROLE IF NOT EXISTS maas_agent_session_runtime;
GRANT SELECT(session_id,owner_id,revision,document),INSERT(session_id,owner_id,revision,document),UPDATE(revision,document)
 ON __MAAS_DATABASE__.agent_sessions_v1 TO maas_agent_session_runtime;
-- Bind an independent account/default role only after authorized effective-role tests.
-- No access to Key, budget, request, slot, usage or publisher tables is granted.
