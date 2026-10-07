CREATE TABLE IF NOT EXISTS program (
    program_id TEXT PRIMARY KEY,
    document JSONB NOT NULL,
    CHECK (
        jsonb_typeof(document) = 'object'
        AND document ? 'program_id'
        AND document ->> 'program_id' = program_id
    )
);
