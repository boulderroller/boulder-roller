import Foundation
import Testing
@testable import BoulderRoller

/// L3.04: capability flags describe availability of shipped capabilities,
/// cache for a bounded interval, and can never enable unknown writes.
struct MobileCapabilityPolicyTests {
    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    private func status(_ json: String) -> SystemStatusResponse {
        try! decoder.decode(SystemStatusResponse.self, from: Data(json.utf8))
    }

    private let rolloutJSON = #"""
        "balance_rollout": {"stage": "s", "cohort": "c", "enabled_actions": [],
                            "action_order": [], "enforced": true,
                            "order_valid": true, "blockers": []}
    """#

    // MARK: Old server / old app compatibility

    @Test func oldServerWithoutBlockKeepsShippedDefaults() {
        let response = status("{\(rolloutJSON)}")
        #expect(response.mobileCapabilities == nil)
        let policy = MobileCapabilityPolicy.from(block: nil, fetchedAt: .now)
        for capability in MobileCapabilityPolicy.Capability.allCases {
            #expect(policy.allows(capability))
        }
    }

    @Test func unknownKeysDecodeButEnableNothing() {
        let response = status(#"""
            {\#(rolloutJSON),
             "mobile_capabilities": {
                "contract_version": "mobile_caps.v1",
                "ride_upload": true,
                "push_registration": true,
                "profile_writes": true,
                "teleportation": true}}
            """#)
        let policy = MobileCapabilityPolicy.from(
            block: response.mobileCapabilities, fetchedAt: .now
        )
        // The allowlist is the whole surface — nothing new became a write.
        #expect(MobileCapabilityPolicy.Capability.allCases.count == 3)
        #expect(policy.allows(.rideUpload))
    }

    // MARK: Explicit disable and rollback

    @Test func explicitDisableFailsClosedAndRollbackRestores() {
        let disabled = status(#"""
            {\#(rolloutJSON),
             "mobile_capabilities": {
                "contract_version": "mobile_caps.v1",
                "ride_upload": false,
                "push_registration": true,
                "profile_writes": true}}
            """#)
        let killPolicy = MobileCapabilityPolicy.from(
            block: disabled.mobileCapabilities, fetchedAt: .now
        )
        #expect(killPolicy.verdict(.rideUpload) == .disabled)
        #expect(!killPolicy.allows(.rideUpload))
        #expect(!killPolicy.allowsUnlessDisabled(.rideUpload))
        // Other capabilities are untouched — the switch is narrow.
        #expect(killPolicy.allows(.pushRegistration))

        // Rollback: the next status read restores availability.
        let restored = MobileCapabilityPolicy.from(
            block: MobileCapabilitiesResponse(
                contractVersion: "mobile_caps.v1",
                rideUpload: true, pushRegistration: true, profileWrites: true
            ),
            fetchedAt: .now
        )
        #expect(restored.allows(.rideUpload))
    }

    // MARK: Malformed, outage, and staleness

    @Test func missingFieldInPresentBlockIsUnknownAndRiskyWritesFailClosed() {
        let partial = status(#"""
            {\#(rolloutJSON),
             "mobile_capabilities": {"contract_version": "mobile_caps.v2"}}
            """#)
        let policy = MobileCapabilityPolicy.from(
            block: partial.mobileCapabilities, fetchedAt: .now
        )
        #expect(policy.verdict(.rideUpload) == .unknown)
        #expect(!policy.allows(.rideUpload))
        // Low-risk writes are not silently broken by contract drift.
        #expect(policy.allowsUnlessDisabled(.pushRegistration))
    }

    @Test func neverFetchedIsUnknown() {
        let policy = MobileCapabilityPolicy.neverFetched
        #expect(policy.verdict(.rideUpload) == .unknown)
        #expect(!policy.allows(.rideUpload))
    }

    @Test func staleReadDecaysToUnknownAfterTheDocumentedInterval() {
        let policy = MobileCapabilityPolicy.from(block: nil, fetchedAt: .now)
        let withinTTL = Date.now.addingTimeInterval(MobileCapabilityPolicy.cacheTTLS - 1)
        let beyondTTL = Date.now.addingTimeInterval(MobileCapabilityPolicy.cacheTTLS + 60)
        #expect(policy.allows(.rideUpload, now: withinTTL))
        #expect(policy.verdict(.rideUpload, now: beyondTTL) == .unknown)
        #expect(!policy.allows(.rideUpload, now: beyondTTL))
    }

    // MARK: Store adoption

    @Test func storeAdoptsAndResets() {
        let store = MobileCapabilityStore()
        #expect(store.current().verdict(.rideUpload) == .unknown)
        store.adopt(block: nil)
        #expect(store.current().allows(.rideUpload))
        store.reset()
        #expect(store.current().verdict(.rideUpload) == .unknown)
    }
}
