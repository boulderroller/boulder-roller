//! uniffi-bindgen CLI for generating Swift bindings from this crate.
//!
//! Build/run (never part of the default or iOS builds):
//!   cargo run --no-default-features --features swift-cli --bin uniffi-bindgen -- \
//!     generate --library <libworkout_parse.dylib> --language swift --out-dir <dir>

fn main() {
    uniffi::uniffi_bindgen_main()
}
