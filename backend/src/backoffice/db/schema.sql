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
