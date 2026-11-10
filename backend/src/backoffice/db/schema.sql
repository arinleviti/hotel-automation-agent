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

-- Indexes: lookup structures that keep searches fast as the table grows (with 28 rows Postgres
-- wouldn't need them, but they are what a real deployment uses).
-- HNSW: pgvector's index for "find the vectors closest to this one" (cosine distance).
CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);
-- GIN: Postgres's index for "find the rows containing these words".
CREATE INDEX IF NOT EXISTS chunks_search_text_idx ON chunks USING gin (search_text);
