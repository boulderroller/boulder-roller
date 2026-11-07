import CryptoKit
import Foundation

/// Minimal canonical Solana PDA derivation for the signing firewall.
///
/// Solana chooses the first bump, descending from 255, whose SHA-256 result is
/// not a compressed Edwards25519 point. Merely accepting any bump would let a
/// prepared transaction name a noncanonical account that the on-chain Anchor
/// constraints later reject. The wallet boundary therefore derives the same
/// canonical address before it signs.
enum SolanaProgramAddress {
    static func matchesCanonical(
        _ address: Data,
        seeds: [Data],
        program: Data
    ) -> Bool {
        address.count == 32 && canonicalAddress(seeds: seeds, program: program) == address
    }

    static func canonicalAddress(seeds: [Data], program: Data) -> Data? {
        canonicalAddressAndBump(seeds: seeds, program: program)?.address
    }

    static func canonicalAddressAndBump(seeds: [Data], program: Data) -> (address: Data, bump: UInt8)? {
        guard program.count == 32,
              seeds.count <= 16,
              seeds.allSatisfy({ $0.count <= 32 })
        else {
            return nil
        }

        let marker = Data("ProgramDerivedAddress".utf8)
        for bump in stride(from: 255, through: 0, by: -1) {
            var payload = Data()
            for seed in seeds { payload.append(seed) }
            payload.append(UInt8(bump))
            payload.append(program)
            payload.append(marker)
            let candidate = Data(SHA256.hash(data: payload))
            if !isEd25519CurvePoint(candidate) {
                return (candidate, UInt8(bump))
            }
        }
        return nil
    }

    /// Mirrors the compressed Edwards-Y decompression predicate used by
    /// Solana's `Pubkey::is_on_curve`. Internal visibility keeps fixed parity
    /// vectors testable without exposing field arithmetic to the app.
    static func isEd25519CurvePoint(_ compressed: Data) -> Bool {
        guard compressed.count == 32 else { return false }
        var yBytes = Array(compressed)
        let negativeX = yBytes[31] & 0x80 != 0
        yBytes[31] &= 0x7F
        guard let y = FieldElement(canonicalBytes: yBytes) else { return false }

        // Edwards25519: -x^2 + y^2 = 1 + d*x^2*y^2
        // Therefore x^2 = (y^2 - 1) / (d*y^2 + 1). In a prime field,
        // chi(u / v) == chi(u * v), so one Legendre exponentiation proves
        // whether that quotient has a square root without an inversion.
        let ySquared = y * y
        let u = ySquared - .one
        let v = FieldElement.d * ySquared + .one
        guard !v.isZero else { return false }
        if u.isZero {
            // The unique square root is zero, whose encoded sign must be zero.
            return !negativeX
        }
        return (u * v).legendreSymbol == .one
    }
}

/// Arithmetic modulo 2^255 - 19 in five 51-bit limbs. UInt128 intermediates
/// keep multiplication exact and make the implementation small enough to
/// audit against the standard Edwards25519 formulas.
private struct FieldElement: Equatable {
    private static let radix: UInt64 = 1 << 51
    private static let mask = radix - 1
    private static let modulus = [mask - 18, mask, mask, mask, mask]
    private static let legendreExponent: [UInt64] = [
        0xFFFFFFFFFFFFFFF6,
        0xFFFFFFFFFFFFFFFF,
        0xFFFFFFFFFFFFFFFF,
        0x3FFFFFFFFFFFFFFF,
    ]

    fileprivate static let zero = FieldElement([0, 0, 0, 0, 0])
    fileprivate static let one = FieldElement([1, 0, 0, 0, 0])
    fileprivate static let d = FieldElement([
        929_955_233_495_203,
        466_365_720_129_213,
        1_662_059_464_998_953,
        2_033_849_074_728_123,
        1_442_794_654_840_575,
    ])

    private let limbs: [UInt64]

    private init(_ limbs: [UInt64]) {
        precondition(limbs.count == 5)
        self.limbs = limbs
    }

    fileprivate init?(canonicalBytes bytes: [UInt8]) {
        guard bytes.count == 32 else { return nil }

        // The sign bit has already been removed. Field encodings at or above
        // p are noncanonical and must not decompress as curve points.
        let modulusBytes = [UInt8(0xED)]
            + Array(repeating: UInt8(0xFF), count: 30)
            + [UInt8(0x7F)]
        var comparison = 0
        for index in stride(from: 31, through: 0, by: -1) {
            if bytes[index] < modulusBytes[index] {
                comparison = -1
                break
            }
            if bytes[index] > modulusBytes[index] {
                comparison = 1
                break
            }
        }
        guard comparison < 0 else { return nil }

        func load64(_ offset: Int) -> UInt64 {
            var value: UInt64 = 0
            for index in 0..<8 {
                value |= UInt64(bytes[offset + index]) << UInt64(index * 8)
            }
            return value
        }

        self.init([
            load64(0) & Self.mask,
            (load64(6) >> 3) & Self.mask,
            (load64(12) >> 6) & Self.mask,
            (load64(19) >> 1) & Self.mask,
            (load64(24) >> 12) & Self.mask,
        ])
    }

    fileprivate var isZero: Bool { self == .zero }

    fileprivate var legendreSymbol: FieldElement {
        powered(to: Self.legendreExponent)
    }

    fileprivate static func + (lhs: FieldElement, rhs: FieldElement) -> FieldElement {
        fromWide((0..<5).map { UInt128(lhs.limbs[$0]) + UInt128(rhs.limbs[$0]) })
    }

    fileprivate static func - (lhs: FieldElement, rhs: FieldElement) -> FieldElement {
        let wide = (0..<5).map { index in
            UInt128(lhs.limbs[index])
                + UInt128(Self.modulus[index]) * 2
                - UInt128(rhs.limbs[index])
        }
        return fromWide(wide)
    }

    fileprivate static func * (lhs: FieldElement, rhs: FieldElement) -> FieldElement {
        var wide = Array(repeating: UInt128(0), count: 5)
        for leftIndex in 0..<5 {
            for rightIndex in 0..<5 {
                let product = UInt128(lhs.limbs[leftIndex])
                    * UInt128(rhs.limbs[rightIndex])
                let outputIndex = leftIndex + rightIndex
                if outputIndex < 5 {
                    wide[outputIndex] += product
                } else {
                    wide[outputIndex - 5] += product * 19
                }
            }
        }
        return fromWide(wide)
    }

    private func powered(to exponent: [UInt64]) -> FieldElement {
        var result = Self.one
        var base = self
        for exponentWord in exponent {
            var word = exponentWord
            for _ in 0..<64 {
                if word & 1 == 1 { result = result * base }
                base = base * base
                word >>= 1
            }
        }
        return result
    }

    private static func fromWide(_ input: [UInt128]) -> FieldElement {
        precondition(input.count == 5)
        var wide = input
        let mask = UInt128(Self.mask)

        // Multiplication starts below 2^110 per limb. Six complete carry
        // rounds are more than sufficient to settle the wraparound *19 carry.
        for _ in 0..<6 {
            for index in 0..<4 {
                let carry = wide[index] >> 51
                wide[index] &= mask
                wide[index + 1] += carry
            }
            let carry = wide[4] >> 51
            wide[4] &= mask
            wide[0] += carry * 19
        }

        var reduced = wide.map { UInt64($0) }
        if isAtLeastModulus(reduced) {
            var borrow: UInt64 = 0
            for index in 0..<5 {
                let subtrahend = Self.modulus[index] + borrow
                if reduced[index] >= subtrahend {
                    reduced[index] -= subtrahend
                    borrow = 0
                } else {
                    reduced[index] = Self.radix + reduced[index] - subtrahend
                    borrow = 1
                }
            }
            precondition(borrow == 0)
        }
        return FieldElement(reduced)
    }

    private static func isAtLeastModulus(_ value: [UInt64]) -> Bool {
        for index in stride(from: 4, through: 0, by: -1) {
            if value[index] > modulus[index] { return true }
            if value[index] < modulus[index] { return false }
        }
        return true
    }
}
