// Headless test bridge, compiled with the production firewall/PDA/message files.
// Only the local program and sponsor public-key literals differ in the isolated
// test build. No production runtime override or response-selected policy exists.
import Foundation

func run() throws {
    let input = try JSONSerialization.jsonObject(with: FileHandle.standardInput.readDataToEndOfFile()) as! [String: Any]
    let value = input["intent"] as! [String: Any], wallet = input["wallet"] as! String
    func string(_ name: String) -> String { value[name] as! String }
    func hex(_ text: String) -> Data {
        let a = Array(text)
        return Data(stride(from: 0, to: a.count, by: 2).map { UInt8(String(a[$0...($0 + 1)]), radix: 16)! })
    }
    let intent: Stage1TransactionIntent
    switch string("kind") {
    case "stage1_registration": intent = .registration
    case "stage1_pledge":
        intent = .pledge(hill: string("hill"), climb: string("climb"), mint: string("mint"),
            depositID: UInt64(string("depositId"))!, amount: UInt64(string("amountBaseUnits"))!,
            lockWeeks: UInt16(value["lockWeeks"] as! Int), bonded: string("providerMode") == "bonded",
            backingMints: value["backingMints"] as! [String])
    case "stage1_self_claim":
        precondition(string("claimType") == "cash")
        let leaves = (value["claims"] as! [[String: Any]]).map { item in
            Stage1CashLeaf(leaf: Stage1ClaimLeaf(hill: item["hill"] as! String, week: UInt64(item["week"] as! String)!,
                index: UInt32(item["index"] as! Int), amount: UInt64(item["amountBaseUnits"] as! String)!,
                proof: (item["proof"] as! [[String: Any]]).map { Stage1ClaimProof(hash: hex($0["hash"] as! String), sum: UInt128($0["sum"] as! String)!) }),
                cap: UInt64(item["capBaseUnits"] as! String)!, frozenAt: Int64(item["frozenAt"] as! String)!, auditHash: hex(item["auditHash"] as! String))
        }
        intent = .cashClaim(mint: string("mint"), leaves: leaves, single: value["single"] as? Bool ?? false)
    default: preconditionFailure("Unsupported localnet bridge intent")
    }
    let tables = try (input["lookups"] as? [[String: Any]] ?? []).map { item in
        SolanaTransaction.ResolvedLookupTable(address: try BalanceTransactionFirewall.decodePublicKey(item["address"] as! String),
            authority: try BalanceTransactionFirewall.decodePublicKey(item["authority"] as! String), active: item["active"] as! Bool,
            addresses: try (item["addresses"] as! [String]).map(BalanceTransactionFirewall.decodePublicKey))
    }
    let prepared = input["prepared"] as! [String: Any]
    try BalanceTransactionFirewall.validate(transactionB64: prepared["transaction"] as! String,
        intent: .stage1(intent, wallet: wallet), lookupTables: tables)
    print("{\"ios\":true}")
}
do { try run() } catch { fputs("Native client refused prepared transaction: \(error)\n", stderr); exit(1) }
