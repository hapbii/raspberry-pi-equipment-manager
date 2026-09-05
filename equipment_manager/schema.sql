PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS equipment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    total_qty INTEGER NOT NULL CHECK (total_qty >= 0),
    available_qty INTEGER NOT NULL CHECK (available_qty >= 0 AND available_qty <= total_qty),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scan_sessions (
    token TEXT PRIMARY KEY,
    equipment_id INTEGER NOT NULL REFERENCES equipment(id),
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT
);

CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL,
    equipment_id INTEGER NOT NULL REFERENCES equipment(id),
    action TEXT NOT NULL CHECK (action IN ('loan', 'return')),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    confidence REAL,
    scan_token TEXT REFERENCES scan_sessions(token),
    created_at TEXT NOT NULL,
    due_date TEXT,
    reversed_at TEXT,
    reversed_by TEXT
);

CREATE TABLE IF NOT EXISTS active_loans (
    loan_transaction_id TEXT PRIMARY KEY REFERENCES transactions(id) ON DELETE CASCADE,
    student_id TEXT NOT NULL,
    equipment_id INTEGER NOT NULL REFERENCES equipment(id),
    original_quantity INTEGER NOT NULL CHECK (original_quantity > 0),
    remaining_quantity INTEGER NOT NULL CHECK (
        remaining_quantity >= 0 AND remaining_quantity <= original_quantity
    ),
    due_date TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS return_allocations (
    return_transaction_id TEXT NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    loan_transaction_id TEXT NOT NULL REFERENCES active_loans(loan_transaction_id) ON DELETE CASCADE,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    PRIMARY KEY (return_transaction_id, loan_transaction_id)
);

CREATE TABLE IF NOT EXISTS device_status (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    device_name TEXT NOT NULL,
    detector_mode TEXT NOT NULL,
    model_name TEXT,
    last_seen TEXT NOT NULL,
    last_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_transactions_created_at
ON transactions(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_transactions_student_equipment
ON transactions(student_id, equipment_id);

CREATE INDEX IF NOT EXISTS idx_active_loans_student_due
ON active_loans(student_id, due_date);

CREATE INDEX IF NOT EXISTS idx_scan_sessions_expires
ON scan_sessions(expires_at);
