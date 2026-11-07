-- Add processing status and error tracking to rides
ALTER TABLE rides
    ADD COLUMN IF NOT EXISTS processing_status VARCHAR(20) DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS error_message TEXT,
    ADD COLUMN IF NOT EXISTS file_type VARCHAR(10),
    ADD COLUMN IF NOT EXISTS dung_minted INT,
    ADD COLUMN IF NOT EXISTS tx_signature VARCHAR(128);

CREATE INDEX IF NOT EXISTS idx_rides_status ON rides(processing_status);
CREATE INDEX IF NOT EXISTS idx_rides_user_status ON rides(user_id, processing_status);
