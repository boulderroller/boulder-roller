//! Error types for workout parsing.

use thiserror::Error;

#[derive(Error, Debug)]
pub enum WpError {
    #[error("Parse error: {0}")]
    Parse(String),

    #[error("Invalid FIT file: {0}")]
    InvalidFit(String),

    #[error("Invalid GPX file: {0}")]
    InvalidGpx(String),

    #[error("Invalid TCX file: {0}")]
    InvalidTcx(String),

    #[error("Decompression limit exceeded: {0}")]
    DecompressionLimitExceeded(String),

    #[error("Duration limit exceeded: {0}")]
    DurationLimitExceeded(String),

    #[error("Invalid timestamp: {0}")]
    InvalidTimestamp(String),

    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    #[error("Zip error: {0}")]
    Zip(String),

    #[error("Unsupported file type: {0}")]
    UnsupportedFileType(String),
}

pub type WpResult<T> = Result<T, WpError>;
