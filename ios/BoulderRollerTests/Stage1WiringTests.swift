import XCTest
@testable import BoulderRoller

@MainActor
final class Stage1WiringTests: XCTestCase {
    private let owner = Stage1Owner(id: "rider-a", wallet: "GmaDrppBC7P5ARKV8g3djiwP89vz1jLK23V2GBjuAEGB")
    private func store() -> Stage1OperationStore { .init(defaults: UserDefaults(suiteName: "stage1-tests-" + UUID().uuidString)!) }
    private func data<T: Decodable>(_ name: String, as type: T.Type = T.self) throws -> T { try Stage1RenderFixtureData.payloads[name]!.decode() }
    private func vectors() throws -> [[String: Any]] { try Stage1TransactionFirewallTests().fixtures() }
    private func plan(_ row: [String: Any]) throws -> Stage1Plan {
        guard case let .stage1(intent, _) = Stage1TransactionFirewallTests().intent(row) else { throw Stage1Error.unavailable }
        let request = try JSONDecoder().decode([String: Stage1JSON].self, from: JSONSerialization.data(withJSONObject: row["request"]!))
        return .init(action: Stage1Action(rawValue: row["action"] as! String)!, request: request, intent: intent,
            lookupTable: (row["lookup"] as? [String: Any])?["address"] as? String)
    }
    private func machine(_ service: Stage1MockService, rpc: Stage1MockRPC? = nil, store: Stage1OperationStore? = nil, scope: Stage1OperationScope = .init(action: .registration)) -> Stage1TransactionModel {
        .init(owner: owner, scope: scope, service: service, rpc: rpc ?? Stage1MockRPC(), store: store ?? self.store(), currentOwner: { self.owner })
    }

    func testRawBackendWireNamesDecodeAndEncodeNestedClaimRequests() throws {
        let raw = try JSONDecoder().decode(Stage1JSON.self, from: Data(#"{"prepared_transaction":{"transaction":"wire","last_valid_block_height":42,"blockhash":"hash","pda":"ref"}}"#.utf8))
        let response: Stage1PreparedResponse = try raw.decode()
        XCTAssertEqual(response.preparedTransaction?.lastValidBlockHeight, 42)
        let body = Stage1JSON.object(["amountBaseUnits": .string("123"), "depositId": .string("7"), "claims": .array([.object(["jobId": .string("job"), "index": .number(1)])])])
        let encoder = JSONEncoder(); encoder.keyEncodingStrategy = .convertToSnakeCase
        let result = try JSONSerialization.jsonObject(with: encoder.encode(body)) as! [String: Any]
        XCTAssertEqual(result["amount_base_units"] as? String, "123")
        XCTAssertEqual(result["deposit_id"] as? String, "7")
        XCTAssertEqual((result["claims"] as? [[String: Any]])?.first?["job_id"] as? String, "job")
    }

    func testAPIClientRechecksGateAndSendsActualSnakeCaseBody() async throws {
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [Stage1WireURLProtocol.self]
        let client = APIClient(configuration: config, sessionCredentials: Stage1MemoryCredentials(), accountMutationPermitted: { _ in true })
        try await client.adoptSession(.init(userId: owner.id, wallet: owner.wallet, accessToken: "offline-token",
            accessExpiresAt: "2099-01-01T00:00:00Z", refreshToken: "offline-refresh", refreshExpiresAt: nil))
        let lock = NSLock()
        var live = false, actions = true, paths: [String] = [], body: [String: Any]?
        Stage1WireURLProtocol.install { request in
            let path = request.url!.path
            return try lock.withLock {
                paths.append(path)
                if path == "/status" { return try JSONEncoder().encode(Stage1JSON.object(["stage1": .object(["live": .bool(live), "actions": .bool(actions)])])) }
                var data = request.httpBody ?? Data()
                if let stream = request.httpBodyStream {
                    stream.open(); defer { stream.close() }
                    var buffer = [UInt8](repeating: 0, count: 2048)
                    while stream.hasBytesAvailable { let n = stream.read(&buffer, maxLength: buffer.count); if n <= 0 { break }; data.append(contentsOf: buffer.prefix(n)) }
                }
                body = try JSONSerialization.jsonObject(with: data) as? [String: Any]
                return Data(#"{"prepared_transaction":{"transaction":"offline","last_valid_block_height":42}}"#.utf8)
            }
        }
        defer { Stage1WireURLProtocol.reset() }
        do {
            _ = try await client.stage1Request("POST", "/stage1/me/pledge/prepare", query: [], body: [:], owner: owner)
            XCTFail("Off must refuse before the Stage 1 request")
        } catch Stage1Error.disabled { }
        XCTAssertEqual(lock.withLock { paths }, ["/status"])
        lock.withLock { live = true }
        let json = try await client.stage1Request("POST", "/stage1/me/pledge/prepare", query: [],
            body: ["depositId": .string("7"), "amountBaseUnits": .string("123"), "lockWeeks": .number(13)], owner: owner)
        let response: Stage1PreparedResponse = try json.decode()
        XCTAssertEqual(response.preparedTransaction?.lastValidBlockHeight, 42)
        XCTAssertEqual(lock.withLock { body?["amount_base_units"] as? String }, "123")
        XCTAssertEqual(lock.withLock { body?["lock_weeks"] as? Int }, 13)
        XCTAssertEqual(lock.withLock { paths }, ["/status", "/status", "/stage1/me/pledge/prepare"])
        lock.withLock { actions = false }
        do {
            _ = try await client.stage1Request("POST", "/stage1/me/pledge/prepare", query: [], body: [:], owner: owner)
            XCTFail("Read-only admission must refuse the action request")
        } catch Stage1Error.actionsDisabled { }
        XCTAssertEqual(lock.withLock { paths.last }, "/status")
        XCTAssertEqual(lock.withLock { paths.count }, 4)
    }

    func testConcurrentPresentersCannotBothSign() async throws {
        let service = Stage1MockService(), row = try vectors()[0]; service.prepared = row["prepared"] as? [String: Any]
        service.holdSigning = true
        let storage = store(), first = machine(service, store: storage), second = machine(service, store: storage)
        await first.prepare(try plan(row)); await second.prepare(try plan(row))
        let task = Task { await first.commit() }
        while service.heldSigning == nil { await Task.yield() }
        await second.commit()
        XCTAssertEqual(service.signCount, 1); XCTAssertEqual(service.submitCount, 0)
        service.heldSigning?.resume(); service.heldSigning = nil; await task.value
        XCTAssertEqual(service.submitCount, 1)
    }

    func testPendingPledgeDoesNotAppearInAnotherAction() async throws {
        let rows = try vectors(), service = Stage1MockService(), storage = store()
        let pledge = try XCTUnwrap(rows.first { $0["action"] as? String == "pledge" })
        service.prepared = pledge["prepared"] as? [String: Any]
        let first = machine(service, store: storage, scope: try .init(plan: plan(pledge)))
        await first.prepare(try plan(pledge)); await first.commit()
        XCTAssertNotNil(first.pending)
        let notice = try XCTUnwrap(rows.first { $0["action"] as? String == "withdrawal-notice" })
        service.prepared = notice["prepared"] as? [String: Any]
        let other = machine(service, store: storage, scope: try .init(plan: plan(notice)))
        await other.prepare(try plan(notice))
        XCTAssertNil(other.pending, "A notice sheet cannot inherit the pledge journal")
        XCTAssertEqual(other.state, .checked, "The unrelated notice remains available")
    }

    func testMissingHillIsCachedWithoutRepeatedGateOrReads() async {
        let service = Stage1MockService(); service.payloads["hill"] = .object(["hill": .null])
        let model = Stage1Model(service: service, rpc: Stage1MockRPC(), store: store())
        await model.load(climbID: "without-stage1", owner: owner)
        let calls = service.requests.count, statuses = service.statusCount
        await model.load(climbID: "without-stage1", owner: owner)
        _ = await model.refreshGate()
        XCTAssertFalse(model.visible)
        XCTAssertEqual(service.requests.count, calls)
        XCTAssertEqual(service.statusCount, statuses)
        await model.load(climbID: "different-climb", owner: owner)
        XCTAssertGreaterThan(service.requests.count, calls)
    }

    func testSectionLoadReconcilesWithoutAnActionSheet() async throws {
        let service = Stage1MockService(), row = try vectors()[0], storage = store()
        service.prepared = row["prepared"] as? [String: Any]
        let transaction = machine(service, store: storage)
        await transaction.prepare(try plan(row)); await transaction.commit()
        let p = try XCTUnwrap(transaction.pending)
        service.operation = .object(["operationId": .string("op"), "actionType": .string("stage1_registration"), "asset": .string("SOL"), "amount": .string("0"),
            "referenceType": .string("stage1"), "referenceId": .string(p.reference), "readState": .string("recorded"),
            "pending": .bool(false), "delayed": .bool(false), "needsReview": .bool(false), "recorded": .bool(true)])
        let section = Stage1Model(service: service, rpc: Stage1MockRPC(), store: storage)
        await section.load(climbID: nil, owner: owner)
        XCTAssertNil(try storage.allPending(owner).first, "Recovery must not depend on opening a sheet")
        XCTAssertEqual(service.signCount, 1); XCTAssertEqual(service.submitCount, 1)
    }

    func testRecoveryRechecksConflictRevisionAfterAwait() async throws {
        for recorded in [false, true] {
            let service = Stage1MockService(), row = try vectors()[0], storage = store(), rpc = Stage1MockRPC()
            service.prepared = row["prepared"] as? [String: Any]; rpc.receipt = .failed
            let model = machine(service, rpc: rpc, store: storage)
            await model.prepare(try plan(row)); await model.commit()
            var newer = try XCTUnwrap(model.pending)
            service.holdOperation = true
            let recovery = Task { await model.reconcile() }
            while service.heldOperation == nil { await Task.yield() }
            let old = newer
            newer.operationID = "winner"; newer.reference = Stage1Plans.zero
            newer.conflict = true; newer.signature = nil; newer.blockhash = nil
            try storage.update(newer, replacing: old)
            service.heldOperation?.resume(returning: operation(old, recorded: recorded)); service.heldOperation = nil
            await recovery.value
            XCTAssertEqual(rpc.receiptCalls, 0, "A rejected signature cannot authorize recovery")
            XCTAssertEqual(try storage.allPending(owner).first?.operationID, "winner")
            XCTAssertEqual(model.pending?.operationID, "winner")
        }
    }

    func testSlowRecoveryDoesNotHideUnrelatedReads() async throws {
        let service = Stage1MockService(), storage = store(), row = try vectors()[0]
        service.prepared = row["prepared"] as? [String: Any]
        let model = machine(service, store: storage)
        await model.prepare(try plan(row)); await model.commit()
        service.holdOperation = true
        let section = Stage1Model(service: service, rpc: Stage1MockRPC(), store: storage)
        let loading = Task { await section.load(climbID: nil, owner: owner) }
        while service.heldOperation == nil { await Task.yield() }
        for _ in 0..<100 { await Task.yield() }
        XCTAssertTrue(section.visible)
        XCTAssertNotNil(section.pay.value, "An operation timeout cannot hide unrelated records")
        service.heldOperation?.resume(returning: operation(try XCTUnwrap(model.pending), recorded: false)); service.heldOperation = nil
        await loading.value
    }

    func testMissingHillFieldIsUnavailableAndCanRetry() async {
        let service = Stage1MockService(); service.payloads["hill"] = .object([:])
        let model = Stage1Model(service: service, rpc: Stage1MockRPC(), store: store())
        await model.load(climbID: "climb", owner: owner)
        service.payloads["hill"] = Stage1RenderFixtureData.payloads["hill"]
        await model.load(climbID: "climb", owner: owner)
        XCTAssertTrue(model.visible); XCTAssertNotNil(model.hill)
    }

    private func operation(_ p: Stage1Pending, recorded: Bool) -> Stage1JSON {
        .object(["operationId": .string(p.operationID ?? "op"), "actionType": .string("stage1_" + p.plan.action.rawValue.replacingOccurrences(of: "-", with: "_")), "asset": .string("SOL"), "amount": .string("0"),
            "referenceType": .string("stage1"), "referenceId": .string(p.reference), "readState": .string(recorded ? "recorded" : "needs_review"),
            "pending": .bool(!recorded), "delayed": .bool(false), "needsReview": .bool(!recorded), "recorded": .bool(recorded)])
    }

    func testRPCUsesConfiguredAndInjectedEndpoints() async throws {
        let configuration = URLSessionConfiguration.ephemeral; configuration.protocolClasses = [Stage1WireURLProtocol.self]
        let session = URLSession(configuration: configuration)
        let lock = NSLock(); var destinations: [URL] = []
        Stage1WireURLProtocol.install { request in
            lock.withLock { destinations.append(request.url!) }
            return Data(#"{"jsonrpc":"2.0","id":1,"result":1234}"#.utf8)
        }
        defer { Stage1WireURLProtocol.reset(); session.invalidateAndCancel() }
        let defaultSlot = try await Stage1RPC(session: session).slot()
        let custom = URL(string: "https://rpc.example.invalid/configured-cluster")!
        let customSlot = try await Stage1RPC(url: custom, session: session).slot()
        XCTAssertEqual(defaultSlot, 1234); XCTAssertEqual(customSlot, 1234)
        XCTAssertEqual(lock.withLock { destinations }, [AppConfig.solanaRPCURL, custom])
        XCTAssertEqual(AppConfig.solanaRPCURL.host, "api.\(AppConfig.solanaNetwork).solana.com")
    }

    func testScopesKeepOtherRecordsAndActionsAvailable() throws {
        let rows = try vectors(), storage = store()
        let pledge = try plan(XCTUnwrap(rows.first { $0["action"] as? String == "pledge" }))
        let scope = try Stage1OperationScope(plan: pledge)
        let pending = Stage1Pending(owner: owner, plan: pledge, clientRequestID: "one", reference: try pledge.reference(wallet: owner.wallet), signature: "sig", blockhash: "hash", claimID: nil, scope: scope)
        try storage.save(pending)
        XCTAssertFalse(try storage.reserveSigning(owner, scope: scope))
        let other = Stage1OperationScope(action: .pledge, record: "another-hill")
        XCTAssertTrue(try storage.reserveSigning(owner, scope: other))
        storage.releaseSigning(owner, scope: other)
        let notice = Stage1OperationScope(action: .notice, record: "another-lot")
        XCTAssertTrue(machine(Stage1MockService(), store: storage, scope: notice).canPrepare)
        XCTAssertFalse(machine(Stage1MockService(), store: storage, scope: scope).canPrepare)
        let claim = try plan(XCTUnwrap(rows.first { $0["name"] as? String == "cash_claim_depth16" }))
        let transport = try plan(XCTUnwrap(rows.first { $0["name"] as? String == "cash_lookup_create" }))
        XCTAssertEqual(try Stage1OperationScope(plan: claim), try Stage1OperationScope(plan: transport))
        let exit = try plan(XCTUnwrap(rows.first { $0["action"] as? String == "complete-withdrawal" }))
        XCTAssertEqual(try Stage1OperationScope(plan: exit).record, exit.request["lot"]?.text)
        XCTAssertEqual(try Stage1OperationScope(plan: exit).detail, exit.request["request"]?.text)
    }

    func testLegacyJournalMigrationPreservesEveryShapeAndNewerRecords() throws {
        for row in try vectors() {
            let defaults = UserDefaults(suiteName: "stage1-migration-" + UUID().uuidString)!
            let storage = Stage1OperationStore(defaults: defaults), p = try plan(row)
            let scope = try Stage1OperationScope(plan: p)
            let original = Stage1Pending(owner: owner, plan: p, clientRequestID: "legacy", reference: "winning-ref", signature: nil, blockhash: nil, claimID: "claim", operationID: "winning-op", conflict: true)
            let bytes = try JSONEncoder().encode(original)
            let key = "br-stage1:\(owner.key):pending"
            let newer = Stage1Pending(owner: owner, plan: p, clientRequestID: "newer", reference: "new-ref", signature: "sig", blockhash: "hash", claimID: nil, scope: scope)
            try storage.save(newer)
            defaults.set(bytes, forKey: key)
            let migrated = try storage.allPending(owner)
            XCTAssertEqual(migrated.count, 2)
            let legacy = try XCTUnwrap(migrated.first { $0.clientRequestID == "legacy" })
            XCTAssertEqual(legacy.scope, scope); XCTAssertEqual(legacy.operationID, "winning-op")
            XCTAssertEqual(legacy.reference, "winning-ref"); XCTAssertEqual(legacy.conflict, true)
            XCTAssertNil(legacy.signature); XCTAssertNil(legacy.blockhash); XCTAssertNil(defaults.data(forKey: key))
            try storage.complete(legacy, confirmed: true)
            XCTAssertEqual(try storage.allPending(owner).map(\.clientRequestID), ["newer"])
            XCTAssertFalse(try storage.clear(legacy))
            XCTAssertFalse(try storage.update(legacy, replacing: legacy))
            XCTAssertTrue(storage.tables(owner).isEmpty)
        }
    }

    func testOnlyLiteralLiveTrueOpensGate() throws {
        for wire in ["{}", #"{"stage1":null}"#, #"{"stage1":{}}"#, #"{"stage1":{"live":false}}"#] {
            XCTAssertFalse(try JSONDecoder().decode(Stage1Status.self, from: Data(wire.utf8)).live)
        }
        for wire in [#"{"stage1":{"live":"true"}}"#, #"{"stage1":{"live":1}}"#] {
            XCTAssertThrowsError(try JSONDecoder().decode(Stage1Status.self, from: Data(wire.utf8)))
        }
    }
    func testReadOnlyAdmissionKeepsReadsButRefusesActionRoutesAndPrepare() async throws {
        let service = Stage1MockService(); service.actionsLive = false
        let model = Stage1Model(service: service, rpc: Stage1MockRPC(), store: store())
        await model.load(climbID: nil, owner: owner)
        XCTAssertTrue(model.visible); XCTAssertNotNil(model.pay.value)
        XCTAssertFalse(service.requests.contains { ["claims", "eligibility", "lookups"].contains(String($0.path.split(separator: "/").last!)) })
        let row = try vectors()[0]; service.prepared = row["prepared"] as? [String: Any]
        let transaction = machine(service)
        await transaction.prepare(try plan(row))
        XCTAssertNil(transaction.checked); XCTAssertEqual(service.signCount, 0)
    }

    func testOpeningReadsDoesNotSimulateEveryPledge() async throws {
        let service = Stage1MockService()
        let model = Stage1Model(service: service, rpc: Stage1MockRPC(), store: store())
        await model.load(climbID: nil, owner: owner)
        XCTAssertNotNil(model.pledges.value)
        XCTAssertFalse(service.requests.contains { $0.path.hasSuffix("/eligibility") })
        let lot = try XCTUnwrap(model.pledges.value?.first)
        XCTAssertNil(lot.chainTime); XCTAssertTrue(Stage1Plans.actions(lot).isEmpty)
        await model.loadLotActions(lot.id)
        XCTAssertEqual(model.pledges.value?.first?.eligibilityWeek, "66")
        service.payloads["eligibility"] = .object(["actions": .object([:]), "chainTime": .string("1800000010"), "week": .string("67")])
        let fresh = try await Stage1Plans.freshLot(lot, service: service, owner: owner)
        XCTAssertEqual(fresh.eligibilityWeek, "67"); XCTAssertEqual(fresh.chainTime, "1800000010")
        XCTAssertEqual(service.requests.filter { $0.path.hasSuffix("/eligibility") }.count, 2)
    }

    func testLookupInventoryRecoversWithoutDeviceStorage() async {
        let service = Stage1MockService()
        service.payloads["lookups"] = .object(["tables": .array([.object(["address": .string(Stage1Plans.zero), "state": .string("active")])]), "nextOffset": .null])
        let model = Stage1Model(service: service, rpc: Stage1MockRPC(), store: store())
        await model.load(climbID: nil, owner: owner)
        XCTAssertEqual(model.transports.value?.map(\.id), [Stage1Plans.zero])
        service.payloads["lookups"] = .object(["tables": .array([]), "nextOffset": .number(50)])
        await model.loadTransports()
        XCTAssertTrue(model.more.contains("lookups")) // A filtered-empty page still has a successor.
        service.payloads["lookups"] = .object(["tables": .array([]), "nextOffset": .null])
        await model.loadMore("lookups")
        XCTAssertTrue(service.requests.contains { $0.path.hasSuffix("/lookups") && $0.query.contains(.init(name: "offset", value: "50")) })
        XCTAssertFalse(model.more.contains("lookups"))
        service.payloads["lookups"] = .object(["tables": .array([]), "nextOffset": .number(50)])
        await model.loadTransports()
        service.payloads["lookups"] = .object(["tables": .array([]), "nextOffset": .null])
        await model.loadTransports()
        XCTAssertFalse(model.more.contains("lookups")) // A fresh inventory replaces the old cursor.
    }

    func testCrossDeviceConflictKeepsJournalAndUsesOnlyWinningOperation() async throws {
      for row in try vectors().filter({ ["registration", "cash_lookup_create"].contains($0["name"] as! String) }) {
        let service = Stage1MockService(), storage = store(), rpc = Stage1MockRPC()
        let plan = try plan(row), reference = Stage1Plans.zero
        service.prepared = row["prepared"] as? [String: Any]
        service.onSubmit = {
            throw APIClient.httpError(status: 409, body: Data("{\"detail\":{\"code\":\"stage1_operation_pending\",\"operation_id\":\"winner\",\"reference_id\":\"\(reference)\"}}".utf8))
        }
        let model = machine(service, rpc: rpc, store: storage, scope: try .init(plan: plan))
        await model.prepare(plan); await model.commit()
        XCTAssertEqual(model.state, .pending)
        XCTAssertEqual(try storage.allPending(owner).first?.operationID, "winner")
        XCTAssertNil(try storage.allPending(owner).first?.signature)
        XCTAssertFalse(model.canPrepare)
        service.operation = .object(["operationId": .string("winner"), "actionType": .string("stage1_" + plan.action.rawValue.replacingOccurrences(of: "-", with: "_")), "asset": .string("SOL"), "amount": .string("0"),
            "referenceType": .string("stage1"), "referenceId": .string(reference), "readState": .string("needs_review"),
            "pending": .bool(false), "delayed": .bool(false), "needsReview": .bool(true), "recorded": .bool(false)])
        await model.reconcile()
        XCTAssertEqual(rpc.receiptCalls, 0); XCTAssertNotNil(model.pending)
        if case var .object(fields) = service.operation! {
            fields["needsReview"] = .bool(false); fields["recorded"] = .bool(true)
            service.operation = .object(fields)
        }
        await model.reconcile()
        XCTAssertNil(model.pending); XCTAssertTrue(storage.tables(owner).isEmpty)
      }
    }

    func testTerminalFailureUnblocksWithoutPollingRejectedSignature() async throws {
        let service = Stage1MockService(), row = try vectors()[0]
        service.prepared = row["prepared"] as? [String: Any]
        let model = machine(service)
        await model.prepare(try plan(row)); await model.commit()
        let reference = try XCTUnwrap(model.pending?.reference)
        service.operation = .object(["operationId": .string("op"), "actionType": .string("stage1_registration"), "asset": .string("SOL"), "amount": .string("0"),
            "referenceType": .string("stage1"), "referenceId": .string(reference), "readState": .string("needs_review"),
            "pending": .bool(false), "delayed": .bool(false), "needsReview": .bool(true), "recorded": .bool(false), "stage1TerminalFailure": .bool(true)])
        await model.reconcile()
        XCTAssertNil(model.pending); XCTAssertTrue(model.canPrepare)
    }

    func testWithdrawalUsesExplicitFreshEligibilityWeek() throws {
        struct Lots: Decodable { let pledges: [Stage1Pledge] }
        var p = try data("pledges", as: Lots.self).pledges[0]
        let w = Stage1Withdrawal(address: "request", parentDepositId: "7", data: .init(requestId: "8", exitLot: p.address, status: 1))
        p.exiting = true; p.exitRequest = w.address; p.withdrawals = [w]
        p.eligibility = ["complete-withdrawal": .init(refreshRate: false)]
        var wire = try JSONSerialization.jsonObject(with: JSONEncoder().encode(p)) as! [String: Any]
        wire["eligibilityWeek"] = "777"
        p = try JSONDecoder().decode(Stage1Pledge.self, from: JSONSerialization.data(withJSONObject: wire))
        let plan = try Stage1Plans.lot(p, action: .completeWithdrawal, lock: 0, requestID: 99, withdrawal: w)
        guard case let .completeWithdrawal(_, _, _, _, week, _) = plan.intent else { return XCTFail() }
        XCTAssertEqual(week, 777)
    }

    func testMondayPauseRefusesWithdrawalPlansFromFreshEligibility() throws {
        struct Lots: Decodable { let pledges: [Stage1Pledge] }
        for action in [Stage1Action.beginWithdrawal, .completeWithdrawal] {
            var lot = try data("pledges", as: Lots.self).pledges[0]
            let completing = action == .completeWithdrawal
            let w = Stage1Withdrawal(address: "request", parentDepositId: "7", data: .init(requestId: "8", exitLot: lot.address, eligibleAt: "1", status: completing ? 1 : 0))
            lot.exiting = completing; lot.pendingRequest = w.address; lot.exitRequest = w.address; lot.withdrawals = [w]
            let snapshot: Stage1EligibilitySnapshot = try Stage1JSON.object([
                "chainTime": .string("1800000000"), "week": .string("66"), "withdrawalsPausedUntil": .string("1800000060"),
                "actions": .object([action.rawValue: .object(["refreshRate": .bool(false)])])]).decode()
            let fresh = try snapshot.applying(to: lot)
            XCTAssertThrowsError(try Stage1Plans.lot(fresh, action: action, lock: 0, requestID: 9, withdrawal: w))
            XCTAssertFalse(Stage1Plans.actions(fresh).contains { $0.action == action })
            if !completing { XCTAssertTrue(Stage1Plans.actions(fresh).contains { $0.action == .cancelNotice }) }
        }
    }

    func testMondayPauseRechecksBeforeSigningAnAlreadyPreparedWithdrawal() async throws {
        for action in [Stage1Action.beginWithdrawal, .completeWithdrawal] {
            let row = try XCTUnwrap(vectors().first { $0["action"] as? String == action.rawValue })
            let service = Stage1MockService(), p = try plan(row)
            service.prepared = row["prepared"] as? [String: Any]
            let model = machine(service, scope: try .init(plan: p))
            await model.prepare(p); XCTAssertNotNil(model.checked)
            service.payloads["eligibility"] = .object(["chainTime": .string("1800000000"), "week": .string("66"),
                "actions": .object([:]), "withdrawalsPausedUntil": .string("1800000060")])
            await model.commit()
            XCTAssertEqual(service.signCount, 0); XCTAssertEqual(service.submitCount, 0)
            XCTAssertNil(model.pending); XCTAssertNil(model.checked)
            XCTAssertEqual(model.state, .withdrawalsPaused)
        }
    }

    func testServerPauseDistinguishesRefusalFromDurablyReservedBytes() async throws {
        let row = try XCTUnwrap(vectors().first { $0["action"] as? String == "begin-withdrawal" }), p = try plan(row)
        for phase in ["prepare", "submit", "reserved"] {
            let service = Stage1MockService(), storage = store(), scope = try Stage1OperationScope(plan: p)
            service.prepared = row["prepared"] as? [String: Any]
            let error = APIError.http(status: 409, code: "stage1_withdrawal_paused", message: nil)
            if phase == "prepare" { service.prepareError = error }
            if phase == "submit" { service.onSubmit = { throw error } }
            if phase == "reserved" {
                service.submitResponse = .object(["operation": .object(["operationId": .string("op")]), "withdrawalsPausedUntil": .string("4102444800")])
            }
            let model = machine(service, store: storage, scope: scope)
            await model.prepare(p); await model.commit()
            if phase == "reserved" {
                XCTAssertNotNil(model.pending); XCTAssertFalse(model.canPrepare)
                let reopened = machine(service, store: storage, scope: scope)
                XCTAssertEqual(reopened.pending?.withdrawalsPausedUntil, "4102444800")
                service.operation = operation(try XCTUnwrap(reopened.pending), recorded: false)
                await reopened.reconcile(); XCTAssertNotNil(reopened.pending)
            } else {
                XCTAssertNil(model.pending); XCTAssertEqual(model.state, .withdrawalsPaused)
                XCTAssertTrue(try storage.allPending(owner).isEmpty)
            }
            XCTAssertEqual(service.signCount, phase == "prepare" ? 0 : 1)
        }
    }
    func testOffOrFailedStatusMakesNoStage1Request() async {
        for fails in [false, true] {
            let service = Stage1MockService(); service.live = false; service.failStatus = fails
            let model = Stage1Model(service: service, rpc: Stage1MockRPC(), store: store())
            await model.load(climbID: "hill", owner: owner)
            XCTAssertFalse(model.visible); XCTAssertTrue(service.requests.isEmpty)
        }
    }
    func testSignedOutClimbReadsOnlyPublicSurfaces() async {
        let service = Stage1MockService(), model = Stage1Model(service: Stage1MockService())
        let publicModel = Stage1Model(service: service, rpc: Stage1MockRPC(), store: store())
        await publicModel.load(climbID: "canon-id", owner: nil)
        XCTAssertTrue(publicModel.visible)
        XCTAssertNotNil(publicModel.bonding.value)
        XCTAssertFalse(service.requests.contains { $0.path.hasPrefix("/stage1/me/") })
        XCTAssertFalse(model.visible)
    }
    func testBondingFailureStaysInItsSectionAndOwnerReadsContinue() async {
        let service = Stage1MockService(); service.failPath = "bonding"
        let model = Stage1Model(service: service, rpc: Stage1MockRPC(), store: store())
        await model.load(climbID: "canon-id", owner: owner)
        XCTAssertTrue(model.visible); XCTAssertNil(model.bonding.value)
        XCTAssertNotNil(model.registration.value); XCTAssertNotNil(model.pay.value)
    }
    func testMissingHillHidesClimbStage1() async {
        let service = Stage1MockService(); service.payloads["hill"] = .object(["hill": .null])
        let model = Stage1Model(service: service, rpc: Stage1MockRPC(), store: store())
        await model.load(climbID: "unknown", owner: owner)
        XCTAssertFalse(model.visible); XCTAssertFalse(service.requests.contains { $0.path.contains("/me/") })
    }
    func testOwnerReadsSeparatePayDungAndStrandedClaims() async {
        let service = Stage1MockService(), model = Stage1Model(service: Stage1MockService())
        let m = Stage1Model(service: service, rpc: Stage1MockRPC(), store: store())
        await m.load(climbID: nil, owner: owner)
        XCTAssertEqual(m.pay.value?.paid.count, 2); XCTAssertEqual(m.dung.value?.paid.count, 1)
        XCTAssertEqual(m.claims.value?.count, 0) // Pending automatic pay never becomes a claim action.
        XCTAssertTrue(service.requests.filter { $0.path.contains("/me/") }.allSatisfy { $0.owner == owner })
        XCTAssertFalse(model.visible)
    }
    func testPaginationHonorsHasMoreAndNextOffset() async {
        let service = Stage1MockService()
        service.payloads["pay"] = .object(["paid": .array([]), "pending": .array([]), "hasMore": .bool(true)])
        service.payloads["claims"] = .object(["claims": .array([]), "nextOffset": .number(71)])
        let model = Stage1Model(service: service, rpc: Stage1MockRPC(), store: store())
        await model.load(climbID: nil, owner: owner)
        await model.loadMore("pay"); await model.loadMore("claims")
        XCTAssertTrue(service.requests.contains { $0.path.hasSuffix("/pay") && $0.query.contains(.init(name: "offset", value: "50")) })
        XCTAssertTrue(service.requests.contains { $0.path.hasSuffix("/claims") && $0.query.contains(.init(name: "offset", value: "71")) })
    }
    func testGateRevocationHidesPreviouslyLoadedData() async {
        let service = Stage1MockService(), model = Stage1Model(service: Stage1MockService())
        let m = Stage1Model(service: service, rpc: Stage1MockRPC(), store: store())
        await m.load(climbID: nil, owner: owner); service.live = false
        let live = await m.refreshGate()
        XCTAssertFalse(live); XCTAssertFalse(m.visible); XCTAssertFalse(model.visible)
    }
    func testLateEligibilityCannotReplaceNextOwnersPledges() async throws {
        let service = Stage1MockService(); service.holdEligibilityFor = owner.id
        let model = Stage1Model(service: service, rpc: Stage1MockRPC(), store: store())
        await model.load(climbID: nil, owner: owner)
        let address = try XCTUnwrap(model.pledges.value?.first?.id)
        let first = Task { await model.loadLotActions(address) }
        while service.held == nil { await Task.yield() }
        let second = Stage1Owner(id: "rider-b", wallet: owner.wallet)
        await model.load(climbID: nil, owner: second)
        let before = try XCTUnwrap(model.pledges.value?.first?.units)
        service.held?.resume(); service.held = nil
        await first.value
        XCTAssertEqual(model.owner, second)
        XCTAssertEqual(model.pledges.value?.first?.units, before)
    }

    func testCancelledEligibilityRefreshCanReopenWithoutStuckLoading() async throws {
        let service = Stage1MockService()
        let section = Stage1Model(service: service, rpc: Stage1MockRPC(), store: store())
        await section.load(climbID: nil, owner: owner)
        let id = try XCTUnwrap(section.pledges.value?.first?.id)
        service.holdEligibilityFor = owner.id
        let refresh = Task { await section.loadLotActions(id) }
        while service.held == nil { await Task.yield() }
        refresh.cancel(); service.held?.resume(); service.held = nil
        await refresh.value
        XCTAssertFalse(section.eligibilityLoading.contains(id))
        service.holdEligibilityFor = nil
        await section.loadLotActions(id)
        XCTAssertNotNil(section.pledges.value?.first?.eligibility)
    }

    func testLatePaginationFailureCannotReplaceNextOwnersData() async {
        for error in [Stage1Error.unavailable, .disabled] {
            let service = Stage1MockService()
            service.payloads["pay"] = .object(["paid": .array([]), "pending": .array([]), "hasMore": .bool(true)])
            let model = Stage1Model(service: service, rpc: Stage1MockRPC(), store: store())
            await model.load(climbID: nil, owner: owner)
            service.holdPageFor = owner.id
            let first = Task { await model.loadMore("pay") }
            while service.heldPage == nil { await Task.yield() }
            let second = Stage1Owner(id: "rider-b", wallet: owner.wallet)
            await model.load(climbID: nil, owner: second)
            XCTAssertTrue(model.loadingMore.isEmpty)
            service.heldPage?.resume(throwing: error); service.heldPage = nil
            await first.value
            XCTAssertEqual(model.owner, second)
            XCTAssertTrue(model.visible); XCTAssertNotNil(model.pay.value)
        }
    }

    func testSupersededGateResponseCannotHideNewLoad() async throws {
        let service = Stage1MockService()
        let model = Stage1Model(service: service, rpc: Stage1MockRPC(), store: store())
        await model.load(climbID: nil, owner: owner)
        service.holdNextStatus = true
        let first = Task { await model.refreshGate() }
        while service.heldStatus == nil { await Task.yield() }
        await model.load(climbID: nil, owner: .init(id: "rider-b", wallet: owner.wallet))
        let disabled = try JSONDecoder().decode(Stage1Status.self, from: Data(#"{"stage1":{"live":false}}"#.utf8))
        service.heldStatus?.resume(returning: disabled); service.heldStatus = nil
        _ = await first.value
        XCTAssertTrue(model.visible)
    }

    func testExactMintFormattingAndUnknownIdentity() {
        let registry = Stage1MintRegistry()
        XCTAssertEqual(registry.amount("1", mint: Stage1MintRegistry.jito), "0.000000001 jitoSOL")
        XCTAssertEqual(registry.amount("1234567", mint: "DpLPBaRuLnBsR3P3meU1tmiNUxreXwskXBebTYKvNGne"), "1.234567 USDC")
        XCTAssertEqual(registry.amount("18446744073709551615", mint: Stage1MintRegistry.dung), "18,446,744,073.709551615 DUNG")
        XCTAssertEqual(registry.amount("123", mint: Stage1Plans.zero), "123 \(Stage1Copy.baseUnits) · \(Stage1Copy.unknownMint)")
        for value in ["", "01", "-1", "1.0", "NaN", "18446744073709551616"] { XCTAssertNil(registry.amount(value, mint: Stage1MintRegistry.dung)) }
        XCTAssertNil(registry.amount(nil, mint: Stage1MintRegistry.jito))
    }
    func testDevnetCityCashMintReadsAsUSDCAndPreparesWithoutATestPoolRead() async throws {
        let cash = "932CwEMTWHDY1BEkV66DKDgngeEypU3JmybWBu4vMh1e"
        XCTAssertEqual(Stage1MintRegistry(testPoolMint: cash).amount("1234567", mint: cash), "1.234567 USDC")
        // Stage1MockRPC refuses every test-pool read, so a checked claim proves none was needed.
        let row = try Stage1TransactionFirewallTests().cashClaim(XCTUnwrap(vectors().first { $0["name"] as? String == "cash_claim_1" }), inMint: cash)
        let service = Stage1MockService(); service.prepared = row["prepared"] as? [String: Any]
        let claim = try plan(row), model = machine(service, scope: try .init(plan: claim))
        await model.prepare(claim)
        XCTAssertEqual(model.state, .checked)
    }
    func testTestPoolDisplayUsesConfiguredIdentityOnly() {
        let registry = Stage1MintRegistry(testPoolMint: Stage1Plans.zero)
        XCTAssertEqual(registry.amount("1000000001", mint: Stage1Plans.zero), "1.000000001 \(Stage1Copy.testPool)")
        XCTAssertEqual(registry.token(Stage1MintRegistry.jito)?.symbol, "jitoSOL")
        XCTAssertNil(registry.token("not-a-mint"))
    }
    func testAmountInputDoesNotRoundOrOverflow() {
        let locale = Locale(identifier: "en_US_POSIX")
        XCTAssertEqual(Stage1Numbers.baseUnits("18446744073.709551615", decimals: 9, locale: locale), UInt64.max)
        XCTAssertEqual(Stage1Numbers.baseUnits("1,234567", decimals: 6, locale: Locale(identifier: "de_DE")), 1234567)
        for s in ["18446744073.709551616", "0.0000000001", "1e2", "-1", "1,000", "1 000", ".5"] {
            XCTAssertNil(Stage1Numbers.baseUnits(s, decimals: 9, locale: locale), s)
        }
    }
    func testBackingOmitsIneligibleAndAbstainsOnMissing() throws {
        var b: Stage1Bonding = try data("bonding")
        XCTAssertEqual(Stage1MintRegistry.backing(b.assets), "124567890123")
        b.assets[0].backingEligible = false; XCTAssertNil(Stage1MintRegistry.backing(b.assets))
        b.assets[0].backingEligible = true; b.assets[0].backingLamports = nil
        XCTAssertNil(Stage1MintRegistry.backing(b.assets))
    }
    func testRegistrationRequiresExplicitUnregisteredRead() throws {
        var raw = Stage1RenderFixtureData.payloads["registration"]!
        let r: Stage1Registration = try raw.decode(); XCTAssertEqual(try Stage1Plans.registration(r).action, .registration)
        raw = .object(["registration": .object(["person": .string(owner.wallet), "recipient": .string(owner.wallet), "registeredAt": .string("1")]), "held": .array([])])
        XCTAssertThrowsError(try Stage1Plans.registration(raw.decode()))
        XCTAssertThrowsError(try Stage1JSON.object(["held": .array([])]).decode(Stage1Registration.self))
    }
    func testLotActionsRespectLocksNoticeAndEligibility() throws {
        struct Lots: Decodable { let pledges: [Stage1Pledge] }
        var p = try data("pledges", as: Lots.self).pledges[0]
        XCTAssertEqual(Stage1Plans.actions(p).map(\.action), [.notice])
        p.lockEnd = "1800000001"; XCTAssertTrue(Stage1Plans.actions(p).isEmpty)
        p.hillState?.bonded = false; XCTAssertEqual(Stage1Plans.actions(p).map(\.action), [.cancelPledge])
        p.hillState?.bonded = true; p.founding = false; p.sequence = "7"
        XCTAssertEqual(Stage1Plans.actions(p).map(\.action), [.cancelPledge])
        p.eligibility = ["convert-pledge": .init(refreshRate: false)]
        XCTAssertEqual(Stage1Plans.actions(p).map(\.action), [.cancelPledge, .convert])
        p.cityState?.intakePaused = true; XCTAssertEqual(Stage1Plans.actions(p).map(\.action), [.cancelPledge])
        p.cancelled = true; XCTAssertTrue(Stage1Plans.actions(p).isEmpty)
    }
    func testExitPlanUsesParentDepositAndViewedWeek() throws {
        struct Lots: Decodable { let pledges: [Stage1Pledge] }
        var p = try data("pledges", as: Lots.self).pledges[0]
        let w = Stage1Withdrawal(address: "request", parentDepositId: "7", data: .init(requestId: "8", exitLot: p.address, status: 1))
        p.depositId = "999"; p.exiting = true; p.exitRequest = w.address; p.withdrawals = [w]
        p.eligibility = ["complete-withdrawal": .init(refreshRate: false)]
        p.eligibilityWeek = "66"
        let plan = try Stage1Plans.lot(p, action: .completeWithdrawal, lock: 0, requestID: 99, withdrawal: w)
        guard case let .completeWithdrawal(_, _, id, request, week, refresh) = plan.intent else { return XCTFail() }
        XCTAssertEqual(id, 7); XCTAssertEqual(request, 8); XCTAssertEqual(week, (1800000000 - 1760000000) / 604800); XCTAssertFalse(refresh)
    }
    func testPledgeUsesInputAmountLockAndProviderSlots() throws {
        var b: Stage1Bonding = try data("bonding"); b.bonded = false; b.hillState?.bonded = false
        for lock in Stage1Plans.locks {
            let p = try Stage1Plans.pledge(b, registry: .init(), mint: Stage1MintRegistry.jito, amount: 1000000001, lock: lock, depositID: 7)
            guard case let .pledge(_, _, _, id, amount, weeks, bonded, backing) = p.intent else { return XCTFail() }
            XCTAssertEqual(id, 7); XCTAssertEqual(amount, 1000000001); XCTAssertEqual(weeks, lock); XCTAssertFalse(bonded)
            XCTAssertEqual(backing, [Stage1MintRegistry.jito])
        }
        XCTAssertThrowsError(try Stage1Plans.pledge(b, registry: .init(), mint: Stage1MintRegistry.jito, amount: 0, lock: 0, depositID: 7))
        b.cityState?.intakePaused = true
        XCTAssertThrowsError(try Stage1Plans.pledge(b, registry: .init(), mint: Stage1MintRegistry.jito, amount: 1, lock: 0, depositID: 7))
    }

    func testPledgeSkipsSponsorCashSharingTheBackedSlot() throws {
        var b: Stage1Bonding = try data("bonding"); b.bonded = false; b.hillState?.bonded = false
        var cash = b.assets[0].config!; cash.mint = BalanceTransactionFirewall.stage1CashMint; cash.adapter = 254
        b.assets.append(.init(config: cash, mint: cash.mint, backingLamports: nil, backingEligible: false, weekPool: nil))
        let p = try Stage1Plans.pledge(b, registry: .init(), mint: Stage1MintRegistry.jito, amount: 1, lock: 0, depositID: 7)
        guard case let .pledge(_, _, _, _, _, _, _, backing) = p.intent else { return XCTFail() }
        XCTAssertEqual(backing, [Stage1MintRegistry.jito])
    }

    func testEveryPreparedActionIsCheckedBeforeTheCommitStep() async throws {
        for row in try vectors() {
            let service = Stage1MockService(); service.prepared = row["prepared"] as? [String: Any]
            let rpc = Stage1MockRPC(row: row), m = machine(service, rpc: rpc, scope: try .init(plan: plan(row)))
            await m.prepare(try plan(row))
            XCTAssertEqual(m.state, .checked, row["name"] as! String)
            XCTAssertEqual(service.signCount, 0); XCTAssertEqual(service.submitCount, 0)
        }
    }
    func testEveryActionRefusesMismatchingBytesBeforeSigningEvenWithEchoedIntent() async throws {
        for row in try vectors() {
            let service = Stage1MockService(); var prepared = row["prepared"] as! [String: Any]
            var wire = Data(base64Encoded: prepared["transaction"] as! String)!
            wire[wire.count - 1] ^= 1; prepared["transaction"] = wire.base64EncodedString(); service.prepared = prepared
            let m = machine(service, rpc: .init(row: row), scope: try .init(plan: plan(row))); await m.prepare(try plan(row)); await m.commit()
            XCTAssertEqual(m.state, .unavailable, row["name"] as! String)
            XCTAssertEqual(service.signCount, 0); XCTAssertEqual(service.submitCount, 0)
        }
    }
    func testPreparedMetadataCannotRedirectOperationOrBlockhash() async throws {
        let row = try vectors()[0]
        for field in ["pda", "blockhash", "lastValidBlockHeight"] {
            let service = Stage1MockService(); service.prepared = row["prepared"] as? [String: Any]
            service.prepared?[field] = field == "lastValidBlockHeight" ? 0 : "wrong"
            let m = machine(service); await m.prepare(try plan(row)); await m.commit()
            XCTAssertEqual(m.state, .unavailable); XCTAssertEqual(service.signCount, 0)
        }
    }
    func testPendingIsSavedBeforeSendAndLostReplyNeverResigns() async throws {
        let service = Stage1MockService(); let row = try vectors()[0]; service.prepared = row["prepared"] as? [String: Any]
        let storage = store(), m = machine(service, store: storage)
        service.onSubmit = { XCTAssertNotNil(try storage.allPending(self.owner).first); throw Stage1Error.unavailable }
        await m.prepare(try plan(row)); await m.commit(); await m.commit(); await m.prepare(try plan(row))
        XCTAssertEqual(service.signCount, 1); XCTAssertEqual(service.submitCount, 1); XCTAssertEqual(m.state, .needsReview)
        let reopened = machine(service, store: storage)
        XCTAssertNotNil(reopened.pending); XCTAssertFalse(reopened.canPrepare)
        XCTAssertNil(try storage.allPending(.init(id: "other", wallet: owner.wallet)).first)
    }
    func testAccountChangeBetweenPrepareAndHoldRefusesSigning() async throws {
        let service = Stage1MockService(), row = try vectors()[0]; service.prepared = row["prepared"] as? [String: Any]
        var current: Stage1Owner? = owner
        let m = Stage1TransactionModel(owner: owner, scope: .init(action: .registration), service: service, rpc: Stage1MockRPC(), store: store(), currentOwner: { current })
        await m.prepare(try plan(row)); current = nil; await m.commit()
        XCTAssertEqual(service.signCount, 0); XCTAssertEqual(service.submitCount, 0)
    }
    func testDisabledAfterPrepareRefusesSigning() async throws {
        let service = Stage1MockService(), row = try vectors()[0]; service.prepared = row["prepared"] as? [String: Any]
        let m = machine(service); await m.prepare(try plan(row)); service.live = false; await m.commit()
        XCTAssertEqual(service.signCount, 0); XCTAssertEqual(service.submitCount, 0)
    }
    func testOperationStatusConfirmsOnlyMatchingReference() async throws {
        let service = Stage1MockService(), row = try vectors()[0]; service.prepared = row["prepared"] as? [String: Any]
        let storage = store(), m = machine(service, store: storage)
        await m.prepare(try plan(row)); await m.commit()
        let p = try XCTUnwrap(m.pending)
        service.operation = .object(["operationId": .string("op"), "actionType": .string("stage1_registration"), "asset": .string("SOL"), "amount": .string("0"),
            "referenceType": .string("stage1"), "referenceId": .string(p.reference), "readState": .string("recorded"),
            "pending": .bool(false), "delayed": .bool(false), "needsReview": .bool(false), "recorded": .bool(true)])
        await m.reconcile(); XCTAssertEqual(m.state, .confirmed); XCTAssertNil(try storage.allPending(owner).first)
    }
    func testLookupTransportDerivedFromClaimMatchesBackend() throws {
        let rows = try vectors()
        for kind in ["cash", "dung"] {
            let row = rows.first { $0["name"] as? String == kind + "_claim_depth16" }!
            let transport = rows.first { $0["name"] as? String == kind + "_lookup_create" }!
            let intentData = try JSONSerialization.data(withJSONObject: row["intent"]!)
            let d = try JSONDecoder().decode(Stage1Claim.Descriptor.self, from: intentData)
            let claim = Stage1Claim(reference: .init(jobId: "offline", role: 0, index: 0), intent: d, requiresLookup: true)
            let expected = transport["intent"] as! [String: Any]
            let plan = try Stage1Plans.transport(claim, wallet: owner.wallet, slot: UInt64(expected["recentSlot"] as! String)!)
            guard case let .claimTransport(_, table, _, addresses) = plan.intent else { return XCTFail() }
            XCTAssertEqual(table, expected["lookupTable"] as? String); XCTAssertEqual(addresses, expected["addresses"] as? [String])
        }
    }
    func testLookupAuthorityAndWarmthFailClosed() throws {
        let addresses = [try Stage1Address.key(Stage1Plans.zero)]
        let inactive = Stage1Lookup(address: Stage1Plans.zero, authority: owner.wallet, deactivationSlot: 100, lastExtendedSlot: 5, contextSlot: 10, addresses: addresses)
        XCTAssertThrowsError(try inactive.resolved(owner: owner.wallet))
        let fresh = Stage1Lookup(address: Stage1Plans.zero, authority: owner.wallet, deactivationSlot: .max, lastExtendedSlot: 10, contextSlot: 10, addresses: addresses)
        XCTAssertThrowsError(try fresh.resolved(owner: owner.wallet))
        XCTAssertThrowsError(try fresh.resolved(owner: "other"))
    }
}

@MainActor private final class Stage1MockService: Stage1Servicing {
    var actionsLive = true
    struct Request { let path: String; let query: [URLQueryItem]; let owner: Stage1Owner? }
    var requests: [Request] = []
    var payloads = Stage1RenderFixtureData.payloads
    var live = true, failStatus = false
    var statusCount = 0
    var failPath: String?
    var prepared: [String: Any]?
    var prepareError: Error?
    var submitResponse: Stage1JSON?
    var operation: Stage1JSON?
    var signCount = 0, submitCount = 0
    var onSubmit: (() throws -> Void)?
    var holdEligibilityFor: String?
    var held: CheckedContinuation<Void, Never>?
    var holdSigning = false
    var heldSigning: CheckedContinuation<Void, Never>?
    var holdPageFor: String?
    var heldPage: CheckedContinuation<Stage1JSON, Error>?
    var holdNextStatus = false
    var heldStatus: CheckedContinuation<Stage1Status, Error>?
    var holdOperation = false
    var heldOperation: CheckedContinuation<Stage1JSON, Never>?
    func status() async throws -> Stage1Status {
        statusCount += 1
        if holdNextStatus {
            holdNextStatus = false
            return try await withCheckedThrowingContinuation { heldStatus = $0 }
        }
        if failStatus { throw Stage1Error.unavailable }
        return try Stage1JSON.object(["stage1": .object(["live": .bool(live), "actions": .bool(actionsLive)])]).decode()
    }
    func request(_ method: String, _ path: String, query: [URLQueryItem], body: [String: Stage1JSON]?, owner: Stage1Owner?) async throws -> Stage1JSON {
        if owner?.id == holdPageFor, query.contains(.init(name: "offset", value: "50")) {
            return try await withCheckedThrowingContinuation { heldPage = $0 }
        }
        requests.append(.init(path: path, query: query, owner: owner))
        let name = path.split(separator: "/").last.map(String.init)!
        if name == failPath { throw Stage1Error.unavailable }
        if name == "prepare", let prepareError { throw prepareError }
        if name == "prepare", let prepared {
            // A malicious echo does not become the user's intent.
            return try JSONDecoder().decode(Stage1JSON.self, from: JSONSerialization.data(withJSONObject: ["preparedTransaction": prepared, "intent": ["kind": "stage1_registration", "amountBaseUnits": "999999999"]]))
        }
        if path.contains("/balance/") {
            if holdOperation { holdOperation = false; return await withCheckedContinuation { heldOperation = $0 } }
            if let operation { return operation }
        }
        if method == "POST", Stage1Action(rawValue: name) != nil {
            submitCount += 1; try onSubmit?(); return submitResponse ?? .object(["operation": .object(["operationId": .string("op")])])
        }
        if name == "eligibility", owner?.id == holdEligibilityFor { await withCheckedContinuation { held = $0 } }
        if name == "pledges", owner?.id == "rider-b" {
            struct Rows: Codable { var pledges: [Stage1Pledge] }
            var rows: Rows = try payloads[name]!.decode(); rows.pledges[0].units = "999"
            return try JSONDecoder().decode(Stage1JSON.self, from: JSONEncoder().encode(rows))
        }
        guard let result = payloads[name] else { throw Stage1Error.unavailable }; return result
    }
    func sign(_ transaction: String, owner: Stage1Owner, intent: Stage1TransactionIntent, tables: [SolanaTransaction.ResolvedLookupTable], testPool: Stage1TestPool?) async throws -> String {
        signCount += 1
        if holdSigning { await withCheckedContinuation { heldSigning = $0 } }
        var bytes = Data(base64Encoded: transaction)!
        bytes.replaceSubrange(65..<129, with: Data(repeating: 9, count: 64)) // Offline signer spy only.
        return bytes.base64EncodedString()
    }
}

private final class Stage1MemoryCredentials: SessionCredentialStore, @unchecked Sendable {
    private let lock = NSLock()
    private var token: String?
    func readRefreshToken() throws -> String? { lock.withLock { token } }
    func saveRefreshToken(_ token: String) throws { lock.withLock { self.token = token } }
    func deleteRefreshToken() throws { lock.withLock { token = nil } }
}
private final class Stage1WireURLProtocol: URLProtocol {
    private static let lock = NSLock()
    private static var handler: ((URLRequest) throws -> Data)?
    static func install(_ value: @escaping (URLRequest) throws -> Data) { lock.withLock { handler = value } }
    static func reset() { lock.withLock { handler = nil } }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        do {
            let callback = try XCTUnwrap(Self.lock.withLock { Self.handler })
            let data = try callback(request)
            client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data); client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    override func stopLoading() {}
}
@MainActor private final class Stage1MockRPC: Stage1RPCServicing {
    var receiptCalls = 0
    var receipt: Stage1Receipt = .pending
    let row: [String: Any]?
    init(row: [String: Any]? = nil) { self.row = row }
    func slot() async throws -> UInt64 { 1000 }
    func lookup(_ address: String) async throws -> Stage1Lookup? {
        if let row, let intent = row["intent"] as? [String: Any], intent["kind"] as? String == "stage1_claim_transport",
           intent["lookupTable"] as? String == address {
            return .init(address: address, authority: row["wallet"] as! String,
                deactivationSlot: intent["mode"] as? String == "close" ? 1 : .max,
                lastExtendedSlot: 1, contextSlot: 2, addresses: [])
        }
        guard let row, let lookup = row["lookup"] as? [String: Any] else { throw Stage1Error.unavailable }
        return .init(address: address, authority: row["wallet"] as! String, deactivationSlot: .max, lastExtendedSlot: 1, contextSlot: 2,
            addresses: try (lookup["addresses"] as! [String]).map(Stage1Address.key))
    }
    func testPool() async throws -> Stage1TestPool { throw Stage1Error.unavailable }
    func settlement(signature: String, blockhash: String) async throws -> Stage1Receipt { receiptCalls += 1; return receipt }
}
