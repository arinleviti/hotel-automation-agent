-- Database structure for the demo. Safe to run any number of times (IF NOT EXISTS).
-- The LangGraph checkpointer creates its own tables later (step 9); they are not defined here.

-- pgvector: the `vector` column type for document embeddings (used from step 6).
CREATE EXTENSION IF NOT EXISTS vector;

-- Agreed prices per supplier and product (source: data/supplier_prices.csv).
CREATE TABLE IF NOT EXISTS supplier_prices (
    supplier  TEXT          NOT NULL,
    code      TEXT          NOT NULL,
    product   TEXT          NOT NULL,
    unit      TEXT          NOT NULL,
    price     NUMERIC(10,2) NOT NULL CHECK (price >= 0),   -- exact decimal: maps to Python Decimal
    PRIMARY KEY (supplier, code)                           -- one price per supplier + product code
);

-- Rooms per night, a snapshot of the booking system (source: data/availability.csv).
CREATE TABLE IF NOT EXISTS availability (
    night         DATE    PRIMARY KEY,                           -- one row per night
    rooms_total   INTEGER NOT NULL CHECK (rooms_total > 0),
    rooms_booked  INTEGER NOT NULL CHECK (rooms_booked >= 0)     -- may exceed rooms_total: overbooking happens
);

-- Room rates (source: data/room_rates.csv), stands for the rates in the hotel's booking system.
-- One row per room type; phase 1 has one: ('Mountain View Room', 185.00, 65.00, 13, 0.1040).
CREATE TABLE IF NOT EXISTS room_rates (
    room_type        TEXT          PRIMARY KEY,
    adult_rate       NUMERIC(10,2) NOT NULL CHECK (adult_rate >= 0),     -- per adult, per night
    child_rate       NUMERIC(10,2) NOT NULL CHECK (child_rate >= 0),     -- per child, per night
    child_under_age  INTEGER       NOT NULL CHECK (child_under_age > 0), -- younger than this = child rate
    tax_rate         NUMERIC(6,4)  NOT NULL CHECK (tax_rate >= 0 AND tax_rate < 1)   -- 0.1040 = 10.4%
);

-- The searchable pieces of the hotel documents (filled by rag/index_documents.py, step 6.4).
-- One row = one chunk. Example row (shortened):
--   id=21, document='overlook_spa_price_list.pdf', chunk_index=4, headings={'Treatments'},
--   text='| Treatment | Duration | Price | ... | Private sauna (up to 4 people) | 60 min | $90 | ...',
--   pages={1,2}, label='Spa price list 2026, Treatments table: extras such as private sauna and spa packages ...',
--   embedding=[0.012, -0.034, ... 1024 numbers ...]
CREATE TABLE IF NOT EXISTS chunks (
    id           SERIAL        PRIMARY KEY,               -- 1, 2, 3 ... assigned by Postgres
    document     TEXT          NOT NULL,                  -- file name
    chunk_index  INTEGER       NOT NULL,                  -- position of the chunk in its document: 0, 1, 2 ...
    headings     TEXT[]        NOT NULL,                  -- an ARRAY (a list in one column), e.g. {'House Rules & Policies','7. Transportation'}
    text         TEXT          NOT NULL,                  -- the chunk's text, unchanged
    pages        INTEGER[]     NOT NULL,                  -- e.g. {1,2}; {} for the Word file (no pages)
    label        TEXT          NOT NULL,                  -- the contextual label written by Claude Haiku
    embedding    vector(1024)  NOT NULL,                  -- the Voyage vector: 1024 numbers (pgvector column type)
    -- Keyword search: Postgres turns label + text into a list of searchable words ("tsvector"),
    -- e.g. 'sauna', 'privat', 'packag' (words are reduced to their stem). GENERATED ... STORED means
    -- Postgres computes and stores it itself whenever a row is written: our code never sets it.
    search_text  tsvector      GENERATED ALWAYS AS (to_tsvector('english', label || ' ' || text)) STORED,
    UNIQUE (document, chunk_index)                        -- a chunk can't be stored twice
);

-- What the action node did with each run's outgoing message, after a staff member decided (step 9.2).
-- One row per run. "Sent" in phase 1 = a row here (no real email leaves); the UI's Sent folder
-- (step 16) = the rows with decision 'approve' or 'edit'. Rejections are recorded too (audit trail),
-- with the draft that was refused. The seed script never empties this table.
-- Example row (email #9, approved):
--   thread_id='6b9a9f43-2c3b-4c13-b22d-1c29be760742', email_name='09_suspicious_hidden_instruction',
--   decision='approve', kind='forward_to_staff',
--   outgoing_to='Front desk <frontdesk@overlook-hotel.example>',
--   outgoing_subject='Needs a person: Re: our stay Dec 5-7', outgoing_body='This email was not answered ...',
--   comment='', decided_at='2026-11-11 15:42:07+01'
CREATE TABLE IF NOT EXISTS actions (
    thread_id         TEXT         PRIMARY KEY,               -- the run: at most ONE row per run (idempotency)
    email_name        TEXT         NOT NULL,                  -- which demo email, e.g. '09_suspicious_hidden_instruction'
    decision          TEXT         NOT NULL CHECK (decision IN ('approve', 'edit', 'reject')),
    kind              TEXT         NOT NULL,                  -- 'reply_to_sender' / 'ok_to_pay' / 'forward_to_staff'
    outgoing_to       TEXT         NOT NULL,
    outgoing_subject  TEXT         NOT NULL,
    outgoing_body     TEXT         NOT NULL,                  -- the FINAL text (the staff member's, if edited)
    comment           TEXT         NOT NULL DEFAULT '',       -- the staff member's note
    decided_at        TIMESTAMPTZ  NOT NULL DEFAULT now()     -- set by Postgres when the row is written
);

-- Every run started from the backend API (step 15): which email, when. The inbox shows each email's
-- LATEST run and its status: no row in `actions` yet = waiting for approval; otherwise the decision.
-- (The run's state itself lives in LangGraph's checkpoint tables, which our code never reads directly.)
-- Step 16.2: each run belongs to ONE visitor of the demo (visitor_id, a random id made by their
-- browser), so every visitor sees only their own inbox status and Sent folder. Runs older than
-- 2 hours are deleted by the API (queries.delete_old_runs).
-- Example row: thread_id='31917ec5-...', email_name='03_booking_complete',
--              started_at='2026-11-13 10:02:11+01', visitor_id='7c1e2b0a-4f5d-4e8a-9a51-3c0d2e9f1b77'
CREATE TABLE IF NOT EXISTS runs (
    thread_id    TEXT         PRIMARY KEY,
    email_name   TEXT         NOT NULL,
    started_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    visitor_id   TEXT         NOT NULL DEFAULT ''        -- '' = started outside the web page (older runs)
);
-- For a database created before step 16.2: add the column if it isn't there yet (idempotent).
ALTER TABLE runs ADD COLUMN IF NOT EXISTS visitor_id TEXT NOT NULL DEFAULT '';
-- "This visitor's runs, newest first per email": the inbox query.
CREATE INDEX IF NOT EXISTS runs_visitor_idx ON runs (visitor_id, email_name, started_at DESC);

-- Indexes: lookup structures that keep searches fast as the table grows (with 28 rows Postgres
-- wouldn't need them, but they are what a real deployment uses).
-- HNSW: pgvector's index for "find the vectors closest to this one" (cosine distance).
CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);
-- GIN: Postgres's index for "find the rows containing these words".
CREATE INDEX IF NOT EXISTS chunks_search_text_idx ON chunks USING gin (search_text);
