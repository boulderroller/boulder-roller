//! Safe decompression with limits to prevent zip bombs.

use crate::constants::*;
use crate::error::{WpError, WpResult};
use flate2::read::GzDecoder;
use std::io::Read;
use zip::ZipArchive;

/// Decompression result - either owned (decompressed) or borrowed (not compressed).
pub enum DecompressResult<'a> {
    Borrowed(&'a [u8]),
    Owned(Vec<u8>),
}

impl<'a> DecompressResult<'a> {
    pub fn as_slice(&self) -> &[u8] {
        match self {
            DecompressResult::Borrowed(s) => s,
            DecompressResult::Owned(v) => v,
        }
    }
}

fn validate_input_size(size: usize) -> WpResult<()> {
    if size > MAX_DECOMPRESSED_SIZE {
        return Err(WpError::DecompressionLimitExceeded(format!(
            "Input size exceeds {} bytes",
            MAX_DECOMPRESSED_SIZE
        )));
    }
    Ok(())
}

/// Decompress data if needed, with safety limits.
/// Returns borrowed slice if not compressed (zero-copy).
pub fn decompress_safe(data: &[u8], depth: usize) -> WpResult<DecompressResult<'_>> {
    if depth > MAX_RECURSION_DEPTH {
        return Err(WpError::DecompressionLimitExceeded(format!(
            "Max recursion depth {} exceeded",
            MAX_RECURSION_DEPTH
        )));
    }

    validate_input_size(data.len())?;

    if data.len() < 4 {
        return Ok(DecompressResult::Borrowed(data));
    }

    // Gzip: 1F 8B
    if data[0] == 0x1F && data[1] == 0x8B {
        let decompressed = decompress_gzip_safe(data)?;
        // Recurse to handle nested compression
        return match decompress_safe(&decompressed, depth + 1)? {
            DecompressResult::Borrowed(_) => Ok(DecompressResult::Owned(decompressed)),
            DecompressResult::Owned(v) => Ok(DecompressResult::Owned(v)),
        };
    }

    // Zip: 50 4B 03 04
    if &data[0..4] == b"PK\x03\x04" {
        let decompressed = decompress_zip_safe(data)?;
        return match decompress_safe(&decompressed, depth + 1)? {
            DecompressResult::Borrowed(_) => Ok(DecompressResult::Owned(decompressed)),
            DecompressResult::Owned(v) => Ok(DecompressResult::Owned(v)),
        };
    }

    // Not compressed - return borrowed reference (zero-copy)
    Ok(DecompressResult::Borrowed(data))
}

fn decompress_gzip_safe(data: &[u8]) -> WpResult<Vec<u8>> {
    let mut decoder = GzDecoder::new(data);
    let mut output = Vec::new();
    let mut buf = [0u8; 65536];
    let input_size = data.len();

    loop {
        let n = decoder.read(&mut buf)?;
        if n == 0 {
            break;
        }

        output.extend_from_slice(&buf[..n]);

        // Size limit
        if output.len() > MAX_DECOMPRESSED_SIZE {
            return Err(WpError::DecompressionLimitExceeded(format!(
                "Decompressed size exceeds {} bytes",
                MAX_DECOMPRESSED_SIZE
            )));
        }

        // Ratio limit
        if input_size > 0 && output.len() / input_size > MAX_COMPRESSION_RATIO {
            return Err(WpError::DecompressionLimitExceeded(format!(
                "Compression ratio exceeds {}x (potential bomb)",
                MAX_COMPRESSION_RATIO
            )));
        }
    }

    Ok(output)
}

fn decompress_zip_safe(data: &[u8]) -> WpResult<Vec<u8>> {
    let cursor = std::io::Cursor::new(data);
    let mut archive = ZipArchive::new(cursor).map_err(|e| WpError::Zip(e.to_string()))?;

    if archive.len() > MAX_ZIP_ENTRIES {
        return Err(WpError::DecompressionLimitExceeded(format!(
            "Zip has {} entries, max is {}",
            archive.len(),
            MAX_ZIP_ENTRIES
        )));
    }

    // Find best candidate file
    let mut best_idx: Option<usize> = None;
    for i in 0..archive.len() {
        let file = archive
            .by_index(i)
            .map_err(|e| WpError::Zip(e.to_string()))?;
        let name = file.name().to_lowercase();

        if name.ends_with(".fit") || name.ends_with(".gpx") || name.ends_with(".tcx") {
            best_idx = Some(i);
            break;
        }
        if best_idx.is_none() && !name.ends_with('/') {
            best_idx = Some(i);
        }
    }

    let idx = best_idx.ok_or_else(|| WpError::Zip("Empty or no suitable files".into()))?;

    let mut file = archive
        .by_index(idx)
        .map_err(|e| WpError::Zip(e.to_string()))?;

    let compressed_size = file.compressed_size() as usize;
    let uncompressed_size = file.size() as usize;

    // Size limit
    if uncompressed_size > MAX_DECOMPRESSED_SIZE {
        return Err(WpError::DecompressionLimitExceeded(format!(
            "Uncompressed size {} exceeds limit",
            uncompressed_size
        )));
    }

    // Ratio limit - use multiplication to avoid div-by-zero
    if uncompressed_size > compressed_size.saturating_mul(MAX_COMPRESSION_RATIO) {
        return Err(WpError::DecompressionLimitExceeded(format!(
            "Zip ratio exceeds {}x (potential bomb)",
            MAX_COMPRESSION_RATIO
        )));
    }

    let mut output = Vec::with_capacity(uncompressed_size.min(MAX_DECOMPRESSED_SIZE));
    let mut buf = [0u8; 65536];

    loop {
        let n = file.read(&mut buf)?;
        if n == 0 {
            break;
        }

        output.extend_from_slice(&buf[..n]);

        if output.len() > MAX_DECOMPRESSED_SIZE {
            return Err(WpError::DecompressionLimitExceeded(format!(
                "Decompressed size exceeds {} bytes",
                MAX_DECOMPRESSED_SIZE
            )));
        }
    }

    Ok(output)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_not_compressed_returns_borrowed() {
        let data = b"hello world";
        let result = decompress_safe(data, 0).unwrap();
        assert!(matches!(result, DecompressResult::Borrowed(_)));
    }

    #[test]
    fn test_uncompressed_input_size_is_bounded() {
        assert!(validate_input_size(MAX_DECOMPRESSED_SIZE).is_ok());
        assert!(matches!(
            validate_input_size(MAX_DECOMPRESSED_SIZE + 1),
            Err(WpError::DecompressionLimitExceeded(_))
        ));
    }
}
