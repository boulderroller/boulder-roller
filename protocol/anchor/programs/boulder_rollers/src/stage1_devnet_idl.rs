// IDL-only wrapper inserted into an isolated source copy, never the ELF source.
    pub fn register_stage1_test_pool(ctx: Context<Stage1RegisterTestPool>) -> Result<()> {
        stage1_devnet::register(ctx)
    }
