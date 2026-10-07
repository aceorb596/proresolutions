CREATE TABLE IF NOT EXISTS pro_quote_requests (
  id UUID PRIMARY KEY,
  payload_hash TEXT NOT NULL,
  payload JSONB NOT NULL,
  subtotal INTEGER NOT NULL CHECK (subtotal > 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  outcome TEXT NOT NULL DEFAULT 'new' CHECK (outcome IN ('new','quoted','booked','lost')),
  delivery TEXT NOT NULL DEFAULT 'pending' CHECK (delivery IN ('pending','sending','sent','needs_review')),
  task_id TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  next_attempt TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_error TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS pro_quote_delivery ON pro_quote_requests(delivery,next_attempt);
CREATE INDEX IF NOT EXISTS pro_quote_created ON pro_quote_requests(created_at);
