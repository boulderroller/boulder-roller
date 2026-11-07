import XCTest
@testable import BoulderRoller

@MainActor
final class BalanceMoneyTruthTests: XCTestCase {
    func testProjectionLagRemainsDelayedAndNeverBecomesDoneFromSubmit() async {
        let service = StubMoneyService()
        service.stakeSubmission = submission(operationId: "op-deposit", projection: "delayed")
        service.statusByOperationId = operationStatus(
            operationId: "op-deposit",
            action: "deposit_cal",
            readState: "delayed"
        )
        let model = makeModel(service: service)

        await model.deposit(vaultId: 42, amount: 250, priorCalBaseUnits: "0", wallet: "wallet")

        XCTAssertEqual(model.status, .delayed)
        XCTAssertEqual(service.operationIdLookups, ["op-deposit"])
        XCTAssertNotEqual(model.status, .done(.deposited))
    }

    func testAmbiguousSubmitLooksUpTheSameClientRequestIdAndNeedsReviewWhenAbsent() async {
        let service = StubMoneyService()
        service.stakeSubmitError = URLError(.networkConnectionLost)
        service.statusByClientRequestId = nil
        let model = makeModel(service: service, requestId: "deposit-stable")

        await model.deposit(vaultId: 42, amount: 250, priorCalBaseUnits: "0", wallet: "wallet")

        XCTAssertEqual(service.stakeSubmitRequestIds, ["deposit-stable"])
        XCTAssertEqual(service.clientRequestIdLookups, ["deposit-stable"])
        XCTAssertEqual(model.supportRequestId, "deposit-stable")
        XCTAssertEqual(model.status, .needsReview)
    }

    func testSessionExpiryAfterSigningReconcilesUsingTheSameClientRequestId() async {
        let service = StubMoneyService()
        service.stakeSubmitError = APIError.notAuthenticated
        service.statusByClientRequestId = operationStatus(
            operationId: "op-session",
            action: "deposit_cal",
            readState: "recorded"
        )
        service.stakes = [stake(vaultId: 42, lpBaseUnits: "250")]
        let model = makeModel(service: service, requestId: "deposit-session")

        await model.deposit(vaultId: 42, amount: 250, priorCalBaseUnits: "0", wallet: "wallet")

        XCTAssertEqual(service.stakeSubmitRequestIds, ["deposit-session"])
        XCTAssertEqual(service.clientRequestIdLookups, ["deposit-session"])
        XCTAssertEqual(service.myStakesCallCount, 1)
        XCTAssertEqual(model.status, .done(.deposited))
    }

    func testRecordedDepositWithMissingPositionRereadRemainsNonfinal() async {
        let service = StubMoneyService()
        service.stakeSubmission = submission(operationId: "op-deposit", projection: "recorded")
        service.statusByOperationId = operationStatus(
            operationId: "op-deposit",
            action: "deposit_cal",
            readState: "recorded"
        )
        service.stakes = []
        let model = makeModel(service: service, timeout: 2, pollInterval: 1)

        await model.deposit(vaultId: 42, amount: 250, priorCalBaseUnits: "0", wallet: "wallet")

        XCTAssertGreaterThanOrEqual(service.myStakesCallCount, 1)
        XCTAssertEqual(model.status, .delayed)
        XCTAssertNotEqual(model.status, .done(.deposited))
    }

    func testRecordedDepositWithUnchangedExistingPositionRereadRemainsNonfinal() async {
        let service = StubMoneyService()
        service.stakeSubmission = submission(operationId: "op-deposit-existing", projection: "recorded")
        service.statusByOperationId = operationStatus(
            operationId: "op-deposit-existing",
            action: "deposit_cal",
            readState: "recorded"
        )
        service.stakes = [stake(vaultId: 42, lpBaseUnits: "100")]
        let model = makeModel(service: service, timeout: 2, pollInterval: 1)

        await model.deposit(
            vaultId: 42,
            amount: 250,
            priorCalBaseUnits: "10",
            wallet: "wallet"
        )

        XCTAssertGreaterThanOrEqual(service.myStakesCallCount, 1)
        XCTAssertEqual(model.status, .delayed)
        XCTAssertNotEqual(model.status, .done(.deposited))
    }

    func testRecordedDepositWithFailedPositionRereadNeedsReview() async {
        let service = StubMoneyService()
        service.stakeSubmission = submission(operationId: "op-deposit-read-failed", projection: "recorded")
        service.statusByOperationId = operationStatus(
            operationId: "op-deposit-read-failed",
            action: "deposit_cal",
            readState: "recorded"
        )
        service.stakesError = BalanceSourceError.unavailable("Positions")
        let model = makeModel(service: service)

        await model.deposit(
            vaultId: 42,
            amount: 250,
            priorCalBaseUnits: "0",
            wallet: "wallet"
        )

        XCTAssertEqual(service.myStakesCallCount, 1)
        XCTAssertEqual(model.status, .needsReview)
        XCTAssertNotEqual(model.status, .done(.deposited))
    }

    func testRecordedDepositRereadFailsClosedOnUnresolvedLegacyIdentity() async {
        let service = StubMoneyService()
        service.stakeSubmission = submission(
            operationId: "op-deposit-unresolved-legacy",
            projection: "recorded"
        )
        service.statusByOperationId = operationStatus(
            operationId: "op-deposit-unresolved-legacy",
            action: "deposit_cal",
            readState: "recorded"
        )
        service.stakes = [
            stake(vaultId: 42, lpBaseUnits: "100"),
            VaultStake(
                vaultSignature: "legacy-other",
                vaultId: nil,
                vaultName: "Other",
                climbId: "climb-other",
                calStaked: "5",
                calStakedBaseUnits: "5000000000",
                lpTokens: "2",
                lpTokensBaseUnits: "2000000000"
            ),
        ]
        service.legacyLookupError = BalanceSourceError.unavailable("Vault identity")
        let model = makeModel(service: service)

        await model.deposit(
            vaultId: 42,
            amount: 250,
            priorCalBaseUnits: "0",
            wallet: "wallet"
        )

        XCTAssertEqual(service.legacySignatureLookups, ["legacy-other"])
        XCTAssertEqual(model.status, .needsReview)
        XCTAssertNotEqual(model.status, .done(.deposited))
    }

    func testKnownPendingOperationTimesOutAsDelayed() async {
        let service = StubMoneyService()
        service.stakeSubmission = submission(operationId: "op-pending", projection: "pending")
        service.statusByOperationId = operationStatus(
            operationId: "op-pending",
            action: "deposit_cal",
            readState: "pending"
        )
        let model = makeModel(service: service, timeout: 2, pollInterval: 1)

        await model.deposit(vaultId: 42, amount: 250, priorCalBaseUnits: "0", wallet: "wallet")

        XCTAssertEqual(model.status, .delayed)
        XCTAssertGreaterThanOrEqual(service.operationIdLookups.count, 2)
    }

    func testCancelledPendingReconciliationStopsAsNeedsReview() async {
        let service = StubMoneyService()
        service.stakeSubmission = submission(operationId: "op-cancelled", projection: "pending")
        service.statusByOperationId = operationStatus(
            operationId: "op-cancelled",
            action: "deposit_cal",
            readState: "pending"
        )
        let model = MoneyModel(
            service: service,
            clock: SelfCancellingClock(),
            timeout: 20,
            pollInterval: 1,
            makeRequestId: { _ in "cancelled-request" }
        )

        let heldAction = Task { @MainActor in
            await model.deposit(
                vaultId: 42,
                amount: 250,
                priorCalBaseUnits: "0",
                wallet: "wallet"
            )
        }
        await heldAction.value

        XCTAssertTrue(heldAction.isCancelled)
        XCTAssertEqual(service.operationIdLookups, ["op-cancelled"])
        XCTAssertEqual(model.status, .needsReview)
        XCTAssertNotEqual(model.status, .done(.deposited))
    }

    func testComposedWithdrawDoesNotIssueASeparateClientHarvest() async {
        let service = StubMoneyService()
        service.pendingByVault[42] = 12
        service.unstakeSubmission = submission(operationId: "op-withdraw", projection: "recorded")
        service.statusByOperationId = operationStatus(
            operationId: "op-withdraw",
            action: "withdraw_cal",
            readState: "recorded"
        )
        service.stakes = []
        let model = makeModel(service: service)

        await model.withdraw(
            vaultId: 42,
            lpAmountBaseUnits: nil,
            priorLpAmountBaseUnits: "100",
            wallet: "wallet"
        )

        XCTAssertEqual(service.collectHarvestVaultIds, [])
        XCTAssertEqual(service.unstakeSubmitRequestIds, ["fixed-request"])
        XCTAssertEqual(service.myStakesCallCount, 1)
        XCTAssertEqual(model.status, .done(.withdrawn))
    }

    func testRecordedWithdrawWithUnchangedPositionRereadRemainsNonfinal() async {
        let service = StubMoneyService()
        service.unstakeSubmission = submission(operationId: "op-withdraw", projection: "recorded")
        service.statusByOperationId = operationStatus(
            operationId: "op-withdraw",
            action: "withdraw_cal",
            readState: "recorded"
        )
        service.stakes = [stake(vaultId: 42, lpBaseUnits: "100")]
        let model = makeModel(service: service, timeout: 2, pollInterval: 1)

        await model.withdraw(
            vaultId: 42,
            lpAmountBaseUnits: nil,
            priorLpAmountBaseUnits: "100",
            wallet: "wallet"
        )

        XCTAssertGreaterThanOrEqual(service.myStakesCallCount, 1)
        XCTAssertEqual(model.status, .delayed)
        XCTAssertNotEqual(model.status, .done(.withdrawn))
    }

    func testRecordedWithdrawRereadRejectsDuplicateDirectAndLegacyMatch() async {
        let service = StubMoneyService()
        service.unstakeSubmission = submission(
            operationId: "op-withdraw-duplicate",
            projection: "recorded"
        )
        service.statusByOperationId = operationStatus(
            operationId: "op-withdraw-duplicate",
            action: "withdraw_cal",
            readState: "recorded"
        )
        service.stakes = [
            stake(vaultId: 42, lpBaseUnits: "100"),
            VaultStake(
                vaultSignature: "legacy-duplicate",
                vaultId: nil,
                vaultName: "The Wall",
                climbId: "climb-42",
                calStaked: "10",
                calStakedBaseUnits: "10000000000",
                lpTokens: "100",
                lpTokensBaseUnits: "100"
            ),
        ]
        let model = makeModel(service: service)

        await model.withdraw(
            vaultId: 42,
            lpAmountBaseUnits: nil,
            priorLpAmountBaseUnits: "100",
            wallet: "wallet"
        )

        XCTAssertEqual(service.legacySignatureLookups, ["legacy-duplicate"])
        XCTAssertEqual(model.status, .needsReview)
        XCTAssertNotEqual(model.status, .done(.withdrawn))
    }

    func testOneCollectFinalizesOnlyAfterRecordedStatusAndPendingRewardsReread() async {
        let service = StubMoneyService()
        service.harvestSubmission = submission(operationId: "op-collect", projection: "recorded")
        service.statusByOperationId = operationStatus(
            operationId: "op-collect",
            action: "collect_dung",
            readState: "recorded"
        )
        service.pendingByVault[42] = 0
        let model = makeModel(service: service)

        await model.collect(vaultId: 42, wallet: "wallet")

        XCTAssertEqual(service.pendingRewardVaultIds, [42])
        XCTAssertEqual(service.signCallCount, 0)
        XCTAssertEqual(service.collectHarvestVaultIds, [42])
        XCTAssertEqual(model.status, .done(.collected))
    }

    func testCollectAllFailsClosedBeforeSubmittingWhenAnySourceReadFails() async {
        let service = StubMoneyService()
        service.stakes = [
            stake(vaultId: 42, lpBaseUnits: "10"),
            stake(vaultId: 43, lpBaseUnits: "20"),
        ]
        service.pendingByVault[42] = 5
        service.pendingReadErrors.insert(43)
        let model = makeModel(service: service)

        await model.collectAll(wallet: "wallet")

        XCTAssertEqual(model.status, .needsReview)
        XCTAssertEqual(service.collectHarvestVaultIds, [])
    }

    func testCollectAllPartialSuccessThenAmbiguousOperationNeedsReview() async {
        let service = StubMoneyService()
        service.stakes = [
            stake(vaultId: 42, lpBaseUnits: "10"),
            stake(vaultId: 43, lpBaseUnits: "20"),
        ]
        service.pendingSequences[42] = [5, 0]
        service.pendingSequences[43] = [6]
        service.harvestSubmissionsByVault[42] = submission(
            operationId: "op-collect-42",
            projection: "recorded"
        )
        service.statusByOperationIds["op-collect-42"] = operationStatus(
            operationId: "op-collect-42",
            action: "collect_dung",
            readState: "recorded"
        )
        service.harvestSubmitErrors[43] = URLError(.networkConnectionLost)
        let model = makeModel(
            service: service,
            requestIds: ["collect-42", "collect-43"]
        )

        await model.collectAll(wallet: "wallet")

        XCTAssertEqual(service.collectHarvestVaultIds, [42, 43])
        XCTAssertEqual(service.harvestSubmitRequestIds, ["collect-42", "collect-43"])
        XCTAssertEqual(service.clientRequestIdLookups, ["collect-43"])
        XCTAssertEqual(model.status, .needsReview)
        XCTAssertNotEqual(model.status, .done(.collected))
    }

    func testCollectAllPriorSuccessThenLaterPermissionlessPostFailureNeedsReview() async {
        let service = StubMoneyService()
        service.stakes = [
            stake(vaultId: 42, lpBaseUnits: "10"),
            VaultStake(
                vaultSignature: "second-signature",
                vaultId: 43,
                vaultName: "Second",
                climbId: "climb-43",
                calStaked: "20",
                calStakedBaseUnits: "20",
                lpTokens: "20",
                lpTokensBaseUnits: "20"
            ),
        ]
        service.pendingSequences[42] = [5, 0]
        service.pendingSequences[43] = [6]
        service.harvestSubmissionsByVault[42] = submission(
            operationId: "op-collect-42",
            projection: "recorded"
        )
        service.statusByOperationIds["op-collect-42"] = operationStatus(
            operationId: "op-collect-42",
            action: "collect_dung",
            readState: "recorded"
        )
        service.harvestSubmitErrors[43] = BalanceSourceError.unavailable("POST")
        let model = makeModel(
            service: service,
            requestIds: ["collect-42", "collect-43"]
        )

        await model.collectAll(wallet: "wallet")

        XCTAssertEqual(service.collectHarvestVaultIds, [42, 43])
        XCTAssertEqual(model.status, .needsReview)
        XCTAssertNotEqual(model.status, .done(.collected))
    }

    func testCollectAllUsesDeployedVaultIdWithoutLegacyDirectoryLookup() async {
        let service = StubMoneyService()
        service.stakes = [stake(vaultId: 42, lpBaseUnits: "10")]
        service.pendingByVault[42] = 0
        let model = makeModel(service: service)

        await model.collectAll(wallet: "wallet")

        XCTAssertEqual(service.legacySignatureLookups, [])
        XCTAssertEqual(service.pendingRewardVaultIds, [42])
        XCTAssertEqual(model.status, .done(.collected))
    }

    func testLegacyStakeIdentityFailsClosedWhenDirectoryCannotResolveIt() async {
        let service = StubMoneyService()
        service.stakes = [stake(vaultId: nil, lpBaseUnits: "10")]
        service.legacyLookupError = BalanceSourceError.unavailable("Vault directory")
        let model = makeModel(service: service)

        await model.collectAll(wallet: "wallet")

        XCTAssertEqual(service.legacySignatureLookups, ["vault-signature"])
        XCTAssertEqual(model.status, .needsReview)
        XCTAssertEqual(service.collectHarvestVaultIds, [])
    }

    func testSubmitModelsPreserveOperationAndProjectionFields() throws {
        let data = Data(
            """
            {
              "vault_signature": "vault",
              "cal_staked": "250",
              "operation_id": "op-123",
              "projection_status": "pending",
              "confirmation_status": "finalized",
              "rider_state": "Pending"
            }
            """.utf8
        )
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase

        let response = try decoder.decode(StakeSubmitResponse.self, from: data)

        XCTAssertEqual(response.operationId, "op-123")
        XCTAssertEqual(response.projectionStatus, "pending")
        XCTAssertEqual(response.confirmationStatus, "finalized")
        XCTAssertEqual(response.riderState, "Pending")
    }

    func testBalanceControlsFollowEnabledPrefixAndFailClosed() {
        let live = BalanceActionAvailability(
            status: SystemStatusResponse(
                balanceRollout: BalanceRolloutStatusResponse(
                    stage: "deposit_cal",
                    cohort: "internal",
                    enabledActions: ["collect_dung", "deposit_cal"],
                    actionOrder: ["collect_dung", "deposit_cal", "withdraw_cal"],
                    enforced: true,
                    orderValid: true,
                    blockers: []
                )
            , mobileCapabilities: nil)
        )
        XCTAssertTrue(live.collect)
        XCTAssertTrue(live.deposit)
        XCTAssertFalse(live.withdraw)

        XCTAssertEqual(BalanceActionAvailability(status: nil), .unavailable)
        XCTAssertEqual(
            BalanceActionAvailability(
                status: SystemStatusResponse(
                    balanceRollout: BalanceRolloutStatusResponse(
                        stage: "deposit_cal",
                        cohort: "internal",
                        enabledActions: ["collect_dung", "deposit_cal"],
                        actionOrder: ["collect_dung", "deposit_cal", "withdraw_cal"],
                        enforced: true,
                        orderValid: true,
                        blockers: ["balance_rollout_owner_missing"]
                    )
                , mobileCapabilities: nil)
            ),
            .unavailable
        )
        XCTAssertEqual(
            BalanceActionAvailability(
                status: SystemStatusResponse(
                    balanceRollout: BalanceRolloutStatusResponse(
                        stage: "withdraw_cal",
                        cohort: "internal",
                        enabledActions: ["collect_dung", "withdraw_cal"],
                        actionOrder: ["collect_dung", "deposit_cal", "withdraw_cal"],
                        enforced: true,
                        orderValid: false,
                        blockers: []
                    )
                , mobileCapabilities: nil)
            ),
            .unavailable
        )
        XCTAssertEqual(
            BalanceActionAvailability(
                status: SystemStatusResponse(
                    balanceRollout: BalanceRolloutStatusResponse(
                        stage: "deposit_cal",
                        cohort: "internal",
                        enabledActions: ["collect_dung", "deposit_cal"],
                        actionOrder: ["collect_dung", "deposit_cal", "withdraw_cal"],
                        enforced: false,
                        orderValid: true,
                        blockers: []
                    )
                , mobileCapabilities: nil)
            ),
            .unavailable
        )
    }

    #if DEBUG
    func testBalanceRenderFixtureRequiresAnExactDebugLaunchArgument() {
        XCTAssertEqual(
            BalanceRenderFixtureMode(
                arguments: ["BoulderRoller", "-BRBalanceRenderFixture", "climb-rollout"]
            ),
            .climbRollout
        )
        XCTAssertEqual(
            BalanceRenderFixtureMode(
                arguments: ["BoulderRoller", "-BRBalanceRenderFixture", "settlements-collect"]
            ),
            .settlementsCollect
        )
        XCTAssertEqual(
            BalanceRenderFixtureMode(
                arguments: [
                    "BoulderRoller",
                    "-BRBalanceRenderFixture",
                    "settlements-needs-review",
                ]
            ),
            .settlementsNeedsReview
        )
        XCTAssertNil(
            BalanceRenderFixtureMode(
                arguments: ["BoulderRoller", "-BRBalanceRenderFixture", "unknown"]
            )
        )
        XCTAssertNil(BalanceRenderFixtureMode(arguments: ["BoulderRoller"]))

        let currentRollout = BalanceRenderFixtureData.currentRolloutAvailability
        XCTAssertTrue(currentRollout.collect)
        XCTAssertTrue(currentRollout.deposit)
        XCTAssertFalse(currentRollout.withdraw)
    }
    #endif

    func testSettlementAggregateIsUnavailableWhenAnyRequiredReadFails() async {
        let failedStakes = StubMoneyService()
        failedStakes.stakesError = BalanceSourceError.unavailable("Positions")
        let missingStakesTotal = await SettlementTruth.uncollectedTotal(service: failedStakes)
        XCTAssertNil(missingStakesTotal)

        let failedPending = StubMoneyService()
        failedPending.stakes = [stake(vaultId: 42, lpBaseUnits: "10")]
        failedPending.pendingReadErrors.insert(42)
        let missingPendingTotal = await SettlementTruth.uncollectedTotal(service: failedPending)
        XCTAssertNil(missingPendingTotal)

        let failedIdentity = StubMoneyService()
        failedIdentity.stakes = [stake(vaultId: nil, lpBaseUnits: "10")]
        failedIdentity.legacyLookupError = BalanceSourceError.unavailable("Vault identity")
        let missingIdentityTotal = await SettlementTruth.uncollectedTotal(service: failedIdentity)
        XCTAssertNil(missingIdentityTotal)
    }

    func testSettlementAggregateUsesEveryAvailableV11VaultIdentity() async {
        let service = StubMoneyService()
        service.stakes = [
            stake(vaultId: 42, lpBaseUnits: "10"),
            VaultStake(
                vaultSignature: "second-signature",
                vaultId: 43,
                vaultName: "Second",
                climbId: "climb-43",
                calStaked: "20",
                calStakedBaseUnits: "20",
                lpTokens: "20",
                lpTokensBaseUnits: "20"
            ),
        ]
        service.pendingByVault = [42: 2.5, 43: 1.5]

        let total = await SettlementTruth.uncollectedTotal(service: service)

        XCTAssertEqual(total, 4)
        XCTAssertEqual(service.legacySignatureLookups, [])
        XCTAssertEqual(service.pendingRewardVaultIds, [42, 43])
    }

    func testZeroDepositBaselineRequiresEveryLegacyPositionIdentityToResolve() async throws {
        let empty = try await VaultPositionTruthResolver.resolve(
            stakes: [],
            vaultId: 42,
            resolveLegacy: { _ in
                XCTFail("An empty v1.1 result has no legacy identity to resolve")
                return 42
            }
        )
        XCTAssertNil(empty.stake)
        XCTAssertEqual(empty.depositPriorCalBaseUnits, "0")

        let legacy = VaultStake(
            vaultSignature: "legacy-other",
            vaultId: nil,
            vaultName: "Other",
            climbId: "climb-other",
            calStaked: "10",
            calStakedBaseUnits: "10000000000",
            lpTokens: "5",
            lpTokensBaseUnits: "5000000000"
        )
        var resolvedSignatures: [String] = []

        let truth = try await VaultPositionTruthResolver.resolve(
            stakes: [legacy],
            vaultId: 42,
            resolveLegacy: { signature in
                resolvedSignatures.append(signature)
                return 99
            }
        )

        XCTAssertNil(truth.stake)
        XCTAssertEqual(truth.depositPriorCalBaseUnits, "0")
        XCTAssertEqual(resolvedSignatures, ["legacy-other"])
    }

    func testUnrelatedLegacyIdentityFailureKeepsDepositBaselineUnavailable() async {
        let legacy = VaultStake(
            vaultSignature: "legacy-other",
            vaultId: nil,
            vaultName: "Other",
            climbId: "climb-other",
            calStaked: "10",
            calStakedBaseUnits: "10000000000",
            lpTokens: "5",
            lpTokensBaseUnits: "5000000000"
        )
        do {
            _ = try await VaultPositionTruthResolver.resolve(
                stakes: [legacy],
                vaultId: 42,
                resolveLegacy: { _ in
                    throw BalanceSourceError.unavailable("Vault identity")
                }
            )
            XCTFail("An unresolved legacy row cannot prove an empty position")
        } catch {
            XCTAssertEqual(error.localizedDescription, "Vault identity is unavailable")
        }
    }

    func testDuplicateDirectAndLegacyPositionMatchIsUnavailable() async {
        let direct = VaultStake(
            vaultSignature: "direct",
            vaultId: 42,
            vaultName: "The Wall",
            climbId: "climb-42",
            calStaked: "10",
            calStakedBaseUnits: "10000000000",
            lpTokens: "5",
            lpTokensBaseUnits: "5000000000"
        )
        let legacy = VaultStake(
            vaultSignature: "legacy-duplicate",
            vaultId: nil,
            vaultName: "The Wall",
            climbId: "climb-42",
            calStaked: "10",
            calStakedBaseUnits: "10000000000",
            lpTokens: "5",
            lpTokensBaseUnits: "5000000000"
        )

        do {
            _ = try await VaultPositionTruthResolver.resolve(
                stakes: [direct, legacy],
                vaultId: 42,
                resolveLegacy: { _ in 42 }
            )
            XCTFail("Duplicate current-vault identities cannot select a baseline")
        } catch {
            XCTAssertEqual(error.localizedDescription, "Position identity is unavailable")
        }
    }

    func testExistingPositionWithoutExactBaseUnitsIsUnavailable() async {
        let missingExactAmount = VaultStake(
            vaultSignature: "direct",
            vaultId: 42,
            vaultName: "The Wall",
            climbId: "climb-42",
            calStaked: "10",
            calStakedBaseUnits: nil,
            lpTokens: "5",
            lpTokensBaseUnits: "5000000000"
        )

        do {
            _ = try await VaultPositionTruthResolver.resolve(
                stakes: [missingExactAmount],
                vaultId: 42,
                resolveLegacy: { _ in 42 }
            )
            XCTFail("A human-unit position cannot become an exact deposit baseline")
        } catch {
            XCTAssertEqual(error.localizedDescription, "Position amount is unavailable")
        }
    }

    func testFiniteMoneyDisplayRejectsMissingMalformedAndNonfiniteValues() {
        let unavailable: [String?] = [nil, "not-a-number", "nan", "infinity"]

        for raw in unavailable {
            let amount = FiniteMoneyAmount(raw)
            XCTAssertNil(amount.value)
            XCTAssertFalse(amount.isAvailable)
            XCTAssertEqual(amount.display, "—")
            XCTAssertEqual(amount.calDisplay, "—")
        }

        let available = FiniteMoneyAmount("12")
        XCTAssertEqual(available.value, 12)
        XCTAssertTrue(available.isAvailable)
        XCTAssertEqual(available.display, "12")
        XCTAssertEqual(available.calDisplay, "12 CAL")
    }

    func testResolvedPositionRequiresExactInputsBeforeWithdrawIsExposed() async throws {
        let valid = VaultStake(
            vaultSignature: "vault-42",
            vaultId: 42,
            vaultName: "The Wall",
            climbId: "climb-42",
            calStaked: "10",
            calStakedBaseUnits: "10000000000",
            lpTokens: "5",
            lpTokensBaseUnits: "5000000000"
        )
        let validTruth = try await VaultPositionTruthResolver.resolve(
            stakes: [valid],
            vaultId: 42,
            resolveLegacy: { _ in 42 }
        )
        XCTAssertEqual(validTruth.depositPriorCalBaseUnits, "10000000000")
        XCTAssertEqual(validTruth.withdrawPositionCal, 10)

        let mismatchedHuman = VaultStake(
            vaultSignature: "vault-42",
            vaultId: 42,
            vaultName: "The Wall",
            climbId: "climb-42",
            calStaked: "9",
            calStakedBaseUnits: "10000000000",
            lpTokens: "5",
            lpTokensBaseUnits: "5000000000"
        )
        let mismatchedTruth = try await VaultPositionTruthResolver.resolve(
            stakes: [mismatchedHuman],
            vaultId: 42,
            resolveLegacy: { _ in 42 }
        )
        XCTAssertNil(mismatchedTruth.withdrawPositionCal)
    }

    private func makeModel(
        service: StubMoneyService,
        timeout: TimeInterval = 2,
        pollInterval: TimeInterval = 1,
        requestId: String = "fixed-request",
        requestIds: [String]? = nil
    ) -> MoneyModel {
        let ids = requestIds ?? [requestId]
        var index = 0
        return MoneyModel(
            service: service,
            clock: AdvancingClock(),
            timeout: timeout,
            pollInterval: pollInterval,
            makeRequestId: { _ in
                defer { index += 1 }
                return ids[min(index, ids.count - 1)]
            }
        )
    }

    private func stake(vaultId: Int?, lpBaseUnits: String) -> VaultStake {
        VaultStake(
            vaultSignature: "vault-signature",
            vaultId: vaultId,
            vaultName: "The Wall",
            climbId: "climb-42",
            calStaked: "10",
            calStakedBaseUnits: "10",
            lpTokens: lpBaseUnits,
            lpTokensBaseUnits: lpBaseUnits
        )
    }

    private func submission(
        operationId: String,
        projection: String
    ) -> BalanceSubmissionSnapshot {
        BalanceSubmissionSnapshot(
            operationId: operationId,
            projectionStatus: projection,
            confirmationStatus: "finalized",
            riderState: projection == "recorded" ? "Collected" : "Pending"
        )
    }

    private func operationStatus(
        operationId: String,
        action: String,
        readState: String
    ) -> BalanceOperationStatusResponse {
        BalanceOperationStatusResponse(
            operationId: operationId,
            actionType: action,
            asset: action == "collect_dung" ? "DUNG" : "CAL",
            amount: "250",
            referenceType: "vault",
            referenceId: "42",
            riderState: readState == "recorded" ? "Collected" : "Pending",
            readState: readState,
            pending: readState == "pending",
            delayed: readState == "delayed",
            needsReview: readState == "needs_review",
            recorded: readState == "recorded"
        )
    }
}

private final class AdvancingClock: BalanceReconciliationClock {
    private(set) var now: TimeInterval = 0

    func sleep(seconds: TimeInterval) async {
        now += seconds
    }
}

private final class SelfCancellingClock: BalanceReconciliationClock {
    var now: TimeInterval { 0 }

    func sleep(seconds: TimeInterval) async {
        withUnsafeCurrentTask { task in
            task?.cancel()
        }
    }
}

@MainActor
private final class StubMoneyService: MoneyServicing {
    var stakeSubmission = BalanceSubmissionSnapshot(
        operationId: "op-stake",
        projectionStatus: "recorded",
        confirmationStatus: "finalized",
        riderState: "Pending"
    )
    var unstakeSubmission = BalanceSubmissionSnapshot(
        operationId: "op-unstake",
        projectionStatus: "recorded",
        confirmationStatus: "finalized",
        riderState: "Pending"
    )
    var harvestSubmission = BalanceSubmissionSnapshot(
        operationId: "op-harvest",
        projectionStatus: "recorded",
        confirmationStatus: "finalized",
        riderState: "Collected"
    )
    var stakeSubmitError: Error?
    var statusByOperationId: BalanceOperationStatusResponse?
    var statusByClientRequestId: BalanceOperationStatusResponse?
    var statusByOperationIds: [String: BalanceOperationStatusResponse] = [:]
    var statusByClientRequestIds: [String: BalanceOperationStatusResponse] = [:]
    var stakes: [VaultStake] = []
    var stakesError: Error?
    var pendingByVault: [Int: Decimal] = [:]
    var pendingSequences: [Int: [Decimal]] = [:]
    var pendingReadErrors: Set<Int> = []
    var legacyLookupError: Error?
    var harvestSubmissionsByVault: [Int: BalanceSubmissionSnapshot] = [:]
    var harvestSubmitErrors: [Int: Error] = [:]

    private(set) var stakeSubmitRequestIds: [String] = []
    private(set) var unstakeSubmitRequestIds: [String] = []
    private(set) var harvestSubmitRequestIds: [String] = []
    private(set) var operationIdLookups: [String] = []
    private(set) var clientRequestIdLookups: [String] = []
    private(set) var pendingRewardVaultIds: [Int] = []
    private(set) var legacySignatureLookups: [String] = []
    private(set) var collectHarvestVaultIds: [Int] = []
    private(set) var signCallCount = 0
    private(set) var myStakesCallCount = 0

    func prepareStake(vaultId: Int, calAmount: Int) async throws -> PreparedVaultTransaction {
        prepared(vaultId: vaultId)
    }

    func submitStake(
        vaultId: Int,
        calAmount: Int,
        signedTransaction: String,
        lastValidBlockHeight: Int,
        clientRequestId: String
    ) async throws -> BalanceSubmissionSnapshot {
        stakeSubmitRequestIds.append(clientRequestId)
        if let stakeSubmitError { throw stakeSubmitError }
        return stakeSubmission
    }

    func prepareUnstake(
        vaultId: Int,
        lpAmountBaseUnits: String?
    ) async throws -> PreparedVaultTransaction {
        prepared(vaultId: vaultId)
    }

    func submitUnstake(
        vaultId: Int,
        lpAmountBaseUnits: String?,
        signedTransaction: String,
        lastValidBlockHeight: Int,
        clientRequestId: String
    ) async throws -> BalanceSubmissionSnapshot {
        unstakeSubmitRequestIds.append(clientRequestId)
        return unstakeSubmission
    }

    func collectHarvest(vaultId: Int, clientRequestId: String) async throws -> BalanceSubmissionSnapshot {
        collectHarvestVaultIds.append(vaultId)
        harvestSubmitRequestIds.append(clientRequestId)
        if let error = harvestSubmitErrors[vaultId] { throw error }
        return harvestSubmissionsByVault[vaultId] ?? harvestSubmission
    }

    func sign(transaction: String, wallet: String, intent: BalanceTransactionIntent) async throws -> String {
        signCallCount += 1
        return "signed-\(transaction)"
    }

    func operationStatus(operationId: String) async throws -> BalanceOperationStatusResponse? {
        operationIdLookups.append(operationId)
        return statusByOperationIds[operationId] ?? statusByOperationId
    }

    func operationStatus(
        clientRequestId: String,
        referenceType: String,
        referenceId: String,
        actionType: String
    ) async throws -> BalanceOperationStatusResponse? {
        clientRequestIdLookups.append(clientRequestId)
        return statusByClientRequestIds[clientRequestId] ?? statusByClientRequestId
    }

    func myStakes() async throws -> [VaultStake] {
        myStakesCallCount += 1
        if let stakesError { throw stakesError }
        return stakes
    }

    func pendingRewards(vaultId: Int) async throws -> Decimal {
        pendingRewardVaultIds.append(vaultId)
        if pendingReadErrors.contains(vaultId) {
            throw BalanceSourceError.unavailable("Pending DUNG")
        }
        if var values = pendingSequences[vaultId], !values.isEmpty {
            let value = values.removeFirst()
            pendingSequences[vaultId] = values
            return value
        }
        guard let value = pendingByVault[vaultId] else {
            throw BalanceSourceError.unavailable("Pending DUNG")
        }
        return value
    }

    func resolveLegacyVaultId(signature: String) async throws -> Int {
        legacySignatureLookups.append(signature)
        if let legacyLookupError { throw legacyLookupError }
        return 42
    }

    private func prepared(vaultId: Int) -> PreparedVaultTransaction {
        PreparedVaultTransaction(
            transaction: "prepared-\(vaultId)",
            blockhash: "blockhash",
            lastValidBlockHeight: 100,
            message: nil,
            vaultId: vaultId,
            pda: nil
        )
    }
}
