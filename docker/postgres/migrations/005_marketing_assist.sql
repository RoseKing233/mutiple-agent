-- AI marketing assist for new product listings (Stage 1 UC3/UC4, reduced scope).
-- Generated content is only a candidate: nothing reaches products until the manager saves the form.
CREATE TABLE IF NOT EXISTS marketing_generations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL CHECK (kind IN ('copy', 'image')),
    request JSONB NOT NULL,
    output JSONB,
    status TEXT NOT NULL CHECK (status IN ('succeeded', 'failed')),
    error TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    duration_ms INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS marketing_generations_owner ON marketing_generations(owner_id, created_at DESC);

-- Images live in the database (no extra Docker volume to lose during on-site deployment)
-- and are served publicly by unguessable UUID at /api/media/{id}.
CREATE TABLE IF NOT EXISTS generated_images (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES users(id),
    generation_id UUID REFERENCES marketing_generations(id) ON DELETE SET NULL,
    prompt TEXT NOT NULL,
    model TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    data BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
