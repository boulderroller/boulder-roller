// Localnet-only IDL fragment. scripts/build-stage1-localnet.py inserts these
// wrappers in an isolated source copy before Anchor parses the localnet IDL.
    /// Simulated observation; compiled only in the isolated stage1-localnet build.
    pub fn set_test_lst_rate(
        ctx: Context<Stage1TestRate>,
        n: u64,
        d: u64,
        observed_at: i64,
    ) -> Result<()> {
        stage1::test_rate(ctx, n, d, observed_at)
    }
