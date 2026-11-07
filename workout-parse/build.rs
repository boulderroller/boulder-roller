fn main() {
    // Only wire up Python extension-module link args when the `python`
    // feature is enabled. Swift/iOS builds must not reference libpython.
    if std::env::var_os("CARGO_FEATURE_PYTHON").is_some() {
        pyo3_build_config::add_extension_module_link_args();
    }
}
