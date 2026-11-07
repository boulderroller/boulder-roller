#if DEBUG
import Foundation
import SwiftUI

/// Offline simulator fixtures only. Never an account session or chain proof.
enum Stage1RenderFixtureMode: String {
    case climb, settlements, avatar, wallet, unavailable, off, readOnly, pending, paused
    static var current: Self? {
        let args = ProcessInfo.processInfo.arguments
        guard let i = args.firstIndex(of: "-BRStage1RenderFixture"), args.indices.contains(i + 1) else { return nil }
        return Self(rawValue: args[i + 1])
    }
}

@MainActor enum Stage1RenderFixtureData {
    static let store: Stage1OperationStore = {
        let store = Stage1OperationStore(defaults: UserDefaults(suiteName: "br-stage1-offline-render-" + UUID().uuidString)!)
        if Stage1RenderFixtureMode.current == .pending {
            let owner = Stage1Owner(rider)!
            let bonding: Stage1Bonding = try! payloads["bonding"]!.decode()
            let plan = try! Stage1Plans.pledge(bonding, registry: .init(), mint: Stage1MintRegistry.jito, amount: 1_234_567_891, lock: 26, depositID: 77)
            try! store.save(.init(owner: owner, plan: plan, clientRequestID: "offline-pending-pledge",
                reference: try! plan.reference(wallet: owner.wallet), signature: nil, blockhash: nil, claimID: nil,
                operationID: "offline-pending", scope: try! .init(plan: plan)))
        }
        return store
    }()
    static let wallet = "GmaDrppBC7P5ARKV8g3djiwP89vz1jLK23V2GBjuAEGB"
    static let rider = User(id: "stage1-offline-render", wallet: wallet, username: nil, displayName: nil,
        avatarUrl: nil, email: nil, location: nil, preferredUnits: "imperial", totalRides: nil, totalDistanceKm: nil, totalElevationM: nil)
    static let payloads: [String: Stage1JSON] = try! JSONDecoder().decode([String: Stage1JSON].self, from: Data(raw.utf8))
    static let raw = #"""
{
  "mints": {
    "testPoolMint": null
  },
  "hill": {
    "hill": "Enx5dyA7hkWNAbX4Z3HhAVRk1W5m8TGSTUy9gaKbrASN"
  },
  "bonding": {
    "climb": "D9SNYR1k1MNs3Fha2aww6DSvu43vLtjJuXXah9Q9Fs6m",
    "hill": "Enx5dyA7hkWNAbX4Z3HhAVRk1W5m8TGSTUy9gaKbrASN",
    "hillState": {
      "bonded": true,
      "foundingCutoff": "10",
      "foundingFreshSlots": 7,
      "assetLots": [
        "1",
        "0",
        "0"
      ]
    },
    "cityState": {
      "seasonAnchor": "1760000000",
      "providerSlots": 7,
      "assetCount": 3,
      "intakePaused": false
    },
    "chainTime": "1800000000",
    "chainEpoch": "200",
    "bonded": true,
    "foundingCount": "8",
    "lineLamports": "100000000000",
    "week": 40,
    "assets": [
      {
        "config": {
          "mint": "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",
          "slot": 0,
          "adapter": 2,
          "enabled": true,
          "admittedEpoch": "200",
          "lastFreshUntil": "201",
          "admittedNumerator": "1100000000",
          "admittedDenominator": "1000000000"
        },
        "mint": "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",
        "backingLamports": "124567890123",
        "backingEligible": true,
        "weekPool": {
          "available": "456789012",
          "pool": "90000000",
          "published": false
        }
      }
    ],
    "split": {
      "everyRiderByAscents": 70,
      "topTen": 25,
      "localLegend": 5
    }
  },
  "registration": {
    "registration": null,
    "held": [
      {
        "hill": "Enx5dyA7hkWNAbX4Z3HhAVRk1W5m8TGSTUy9gaKbrASN",
        "climbName": "Barren Hill Road",
        "week": 40,
        "mint": "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",
        "amount": "123456789"
      }
    ]
  },
  "pay": {
    "paid": [
      {
        "hill": "Enx5dyA7hkWNAbX4Z3HhAVRk1W5m8TGSTUy9gaKbrASN",
        "climbName": "Barren Hill Road",
        "week": 40,
        "mint": "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",
        "amount": "123456789"
      },
      {
        "hill": "Enx5dyA7hkWNAbX4Z3HhAVRk1W5m8TGSTUy9gaKbrASN",
        "climbName": "The Wall",
        "week": 40,
        "mint": "DpLPBaRuLnBsR3P3meU1tmiNUxreXwskXBebTYKvNGne",
        "amount": "1234567"
      }
    ],
    "pending": [
      {
        "hill": "Enx5dyA7hkWNAbX4Z3HhAVRk1W5m8TGSTUy9gaKbrASN",
        "climbName": "Barren Hill Road",
        "week": 41,
        "mint": "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",
        "amount": "123456789"
      }
    ],
    "hasMore": false
  },
  "dung": {
    "paid": [
      {
        "hill": "Enx5dyA7hkWNAbX4Z3HhAVRk1W5m8TGSTUy9gaKbrASN",
        "climbName": "Barren Hill Road",
        "week": 40,
        "mint": "CqDFJWLpr49tB8xjHegy5JR5jwMCfmhicjuWawtKLeCk",
        "amount": "12345678901",
        "kind": "dung"
      }
    ],
    "pending": [],
    "hasMore": false
  },
  "pledges": {
    "pledges": [
      {
        "address": "3XeiR7H6KYDYzTG7hY8YjRScxU3A1vFD2PdHi8G8H83T",
        "depositId": "7",
        "hill": "Enx5dyA7hkWNAbX4Z3HhAVRk1W5m8TGSTUy9gaKbrASN",
        "climbName": "Barren Hill Road",
        "mint": "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",
        "units": "12345678901",
        "basisLamports": "12000000000",
        "lockWeeks": 26,
        "lockEnd": "1790000000",
        "founding": true,
        "converted": false,
        "cancelled": false,
        "exiting": false,
        "returnedUnits": "0",
        "pendingRequest": "11111111111111111111111111111111",
        "exitRequest": "11111111111111111111111111111111",
        "sequence": "7",
        "hillState": {
          "bonded": true,
          "foundingCutoff": "10",
          "foundingFreshSlots": 7,
          "assetLots": [
            "1",
            "0",
            "0"
          ]
        },
        "cityState": {
          "seasonAnchor": "1760000000",
          "providerSlots": 7,
          "assetCount": 3,
          "intakePaused": false
        },
        "assetState": {
          "mint": "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",
          "slot": 0,
          "adapter": 2,
          "enabled": true,
          "admittedEpoch": "200",
          "lastFreshUntil": "201",
          "admittedNumerator": "1100000000",
          "admittedDenominator": "1000000000"
        },
        "chainTime": "1800000000",
        "chainEpoch": "200",
        "withdrawals": []
      }
    ]
  },
  "claims": {
    "claims": [],
    "nextOffset": null
  },
  "lookups": { "tables": [], "nextOffset": null },
  "eligibility": {
    "chainTime": "1800000000",
    "week": "66",
    "actions": {
      "convert-pledge": {
        "refreshRate": false
      },
      "begin-withdrawal": {
        "refreshRate": false
      },
      "complete-withdrawal": {
        "refreshRate": false
      }
    }
  }
}
"""#
}

@MainActor struct Stage1FixtureService: Stage1Servicing {
    func status() async throws -> Stage1Status {
        try Stage1JSON.object(["stage1": .object(["live": .bool(Stage1RenderFixtureMode.current != .off),
            "actions": .bool(Stage1RenderFixtureMode.current != .readOnly)])]).decode()
    }
    func request(_ method: String, _ path: String, query: [URLQueryItem], body: [String: Stage1JSON]?, owner: Stage1Owner?) async throws -> Stage1JSON {
        let name = path.split(separator: "/").last.map(String.init) ?? ""
        if path.contains("/balance/"), let owner, let p = try Stage1RenderFixtureData.store.allPending(owner).first {
            return .object(["operationId": .string("offline-pending"), "actionType": .string("stage1_pledge"), "asset": .string("SOL"), "amount": .string("0"),
                "referenceType": .string("stage1"), "referenceId": .string(p.reference), "readState": .string("pending"),
                "pending": .bool(true), "delayed": .bool(false), "needsReview": .bool(false), "recorded": .bool(false)])
        }
        if Stage1RenderFixtureMode.current == .unavailable && name == "bonding" { throw Stage1Error.unavailable }
        if Stage1RenderFixtureMode.current == .paused {
            if name == "eligibility", case var .object(fields) = Stage1RenderFixtureData.payloads[name]! {
                fields["withdrawalsPausedUntil"] = .string(String(Int(Date.now.timeIntervalSince1970) + 60))
                fields["actions"] = .object([:])
                return .object(fields)
            }
            if name == "pledges" {
                struct Lots: Codable { var pledges: [Stage1Pledge] }
                var lots: Lots = try Stage1RenderFixtureData.payloads[name]!.decode()
                var lot = lots.pledges[0]
                let request = Base58.encode(try Stage1Address.pda("s1v1_request", Stage1Address.key(lot.address), Stage1Address.le(UInt64(8))))
                lot.pendingRequest = request
                lot.withdrawals = [.init(address: request, parentDepositId: lot.depositId,
                    data: .init(requestId: "8", lot: lot.address, eligibleAt: "1790000000", status: 0))]
                lots.pledges[0] = lot
                return try JSONDecoder().decode(Stage1JSON.self, from: JSONEncoder().encode(lots))
            }
        }
        guard let data = Stage1RenderFixtureData.payloads[name] else { throw Stage1Error.unavailable }
        return data
    }
    func sign(_ transaction: String, owner: Stage1Owner, intent: Stage1TransactionIntent,
              tables: [SolanaTransaction.ResolvedLookupTable], testPool: Stage1TestPool?) async throws -> String {
        throw Stage1Error.unavailable // Fixtures can never sign or submit.
    }
}
@MainActor struct Stage1FixtureRPC: Stage1RPCServicing {
    func slot() async throws -> UInt64 { throw Stage1Error.unavailable }
    func lookup(_ address: String) async throws -> Stage1Lookup? { throw Stage1Error.unavailable }
    func testPool() async throws -> Stage1TestPool { throw Stage1Error.unavailable }
    func settlement(signature: String, blockhash: String) async throws -> Stage1Receipt { throw Stage1Error.unavailable }
}

@MainActor struct Stage1RenderFixtureRoot: View {
    let mode: Stage1RenderFixtureMode
    @State private var session: AppSession
    init(mode: Stage1RenderFixtureMode) {
        self.mode = mode
        let session = AppSession()
        session.phase = .signedIn(Stage1RenderFixtureData.rider)
        session.balanceActions = BalanceRenderFixtureData.currentRolloutAvailability
        _session = State(initialValue: session)
    }
    var body: some View {
        Group {
            switch mode {
            case .climb, .unavailable, .off, .pending, .paused:
                NavigationStack { ClimbDetailView(renderFixture: BalanceRenderFixtureData.climb) }
            case .settlements:
                SettlementsView(renderFixture: BalanceRenderFixtureData.collectAvailable)
            case .avatar: AvatarSheet()
            case .wallet, .readOnly: WalletSheet()
            }
        }
        .environment(session)
        .defaultScrollAnchor(ProcessInfo.processInfo.arguments.contains("-BRStage1Bottom") ? .bottom : .top)
        .environment(\.dynamicTypeSize, ProcessInfo.processInfo.arguments.contains("-BRStage1Accessibility") ? .accessibility3 : .large)
    }
}
#endif
