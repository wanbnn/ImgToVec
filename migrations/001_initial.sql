CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS videos (
    id                  BIGSERIAL PRIMARY KEY,
    folder_number       INTEGER NOT NULL UNIQUE CHECK (folder_number > 0),
    folder_path         TEXT NOT NULL,
    source_path         TEXT,
    source_sha256       TEXT,
    fps                 DOUBLE PRECISION,
    width               INTEGER,
    height              INTEGER,
    duration_seconds    DOUBLE PRECISION,
    expected_frames     INTEGER,
    discovered_frames   INTEGER NOT NULL DEFAULT 0,
    processed_frames    INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    embedding_model     TEXT,
    last_error          TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at        TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS frames (
    id                  BIGSERIAL PRIMARY KEY,
    video_id            BIGINT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    frame_number        INTEGER NOT NULL CHECK (frame_number > 0),
    relative_path       TEXT NOT NULL,
    file_sha256         TEXT NOT NULL,
    embedding           vector(768),
    embedding_model     TEXT,
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    last_error          TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at        TIMESTAMPTZ,
    UNIQUE (video_id, frame_number)
);

CREATE INDEX IF NOT EXISTS frames_video_status_idx ON frames (video_id, status);
CREATE INDEX IF NOT EXISTS frames_embedding_hnsw_cosine_idx
    ON frames USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;
