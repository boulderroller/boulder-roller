-- Store vault pot token account for epoch distributions

ALTER TABLE indexed_vaults
    ADD COLUMN IF NOT EXISTS vault_pot TEXT;
