ALTER TABLE queue_items
ADD COLUMN auto_submit_enabled INTEGER NOT NULL DEFAULT 0 CHECK (auto_submit_enabled IN (0,1));
