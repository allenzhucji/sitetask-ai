CREATE TABLE IF NOT EXISTS mcp_pairings (
  code_hash TEXT PRIMARY KEY,
  db_id TEXT NOT NULL,
  expires_at INTEGER NOT NULL,
  used_at INTEGER
);
