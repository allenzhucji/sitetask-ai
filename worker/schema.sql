CREATE TABLE IF NOT EXISTS databases(db_id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS api_tokens(token_id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('bridge','submitter')),
  scope TEXT NOT NULL CHECK(scope IN ('bridge','assistant','mail-automation')),db_id TEXT NOT NULL,
  secret_hmac TEXT NOT NULL,label TEXT NOT NULL,revoked_at TEXT);
CREATE TABLE IF NOT EXISTS commands(db_id TEXT NOT NULL,id TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(db_id,id));
CREATE TABLE IF NOT EXISTS task_mirror(db_id TEXT NOT NULL,id TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(db_id,id));
CREATE TABLE IF NOT EXISTS generations(db_id TEXT NOT NULL,id TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(db_id,id));
