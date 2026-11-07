#!/usr/bin/env python3
"""Rent quote from the exact ELF/IDL: explicit RPC, or labeled offline mainnet reference."""
import argparse
import hashlib
import json
import urllib.request
from urllib.parse import urlparse
from pathlib import Path


def size_of(value, definitions):
    if isinstance(value, str):
        return {"bool": 1, "u8": 1, "i8": 1, "u16": 2, "i16": 2, "u32": 4,
                "i32": 4, "u64": 8, "i64": 8, "u128": 16, "i128": 16, "publicKey": 32}[value]
    if "array" in value:
        return value["array"][1] * size_of(value["array"][0], definitions)
    if "option" in value:
        return 1 + size_of(value["option"], definitions)
    if "defined" in value:
        return size_of(definitions[value["defined"]], definitions)
    if value.get("kind") == "enum":
        return 1 + max((sum(size_of(field.get("type", field) if isinstance(field, dict) else field, definitions)
                            for field in variant.get("fields", [])) for variant in value["variants"]), default=0)
    if value.get("kind") == "struct":
        return sum(size_of(field["type"], definitions) for field in value["fields"])
    raise ValueError("Variable account needs its explicit allocation length")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--binary", required=True)
    p.add_argument("--idl", required=True)
    p.add_argument("--current-programdata-bytes", type=int, required=True)
    p.add_argument("--current-programdata-lamports", type=int,
                   help="Actual finalized balance; otherwise assumes current minimum rent")
    p.add_argument('--rpc', help='Explicit cluster RPC for live getMinimumBalanceForRentExemption quotes (read-only)')
    p.add_argument('--before-idl', help='Round 1 IDL for exact before/after weekly account rent')
    p.add_argument('--cash-assets', type=int, default=1, help='Active cash assets per hill-week, including USDC when present')
    args = p.parse_args()
    if args.cash_assets < 1: p.error('At least one active cash asset required')
    elf = Path(args.binary).read_bytes()
    idl = json.loads(Path(args.idl).read_text())
    definitions = {v["name"]: v["type"] for v in idl.get("types", [])}
    # Solana Rent::default(): 3480 lamports/byte-year, 2-year exemption,
    # 128-byte account storage overhead. This is a quote, not live RPC evidence.
    cache = {}
    def rent(length):
        if length in cache: return cache[length]
        if args.rpc:
            url = urlparse(args.rpc)
            if url.username or url.password or url.query or url.fragment or not (url.scheme == 'https' or url.scheme == 'http' and url.hostname in ('127.0.0.1','localhost')):
                p.error('Use an explicit credential-free HTTPS or loopback RPC')
            request = urllib.request.Request(args.rpc, data=json.dumps({'jsonrpc':'2.0','id':1,'method':'getMinimumBalanceForRentExemption','params':[length,{'commitment':'finalized'}]}).encode(), headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(request, timeout=30) as response: result=json.load(response)
            if 'error' in result: raise ValueError(result['error'])
            value=result['result']
            if not isinstance(value,int) or value < 0: raise ValueError('Invalid cluster rent quote')
        else: value=(length+128)*6960
        cache[length]=value
        return value
    old_balance = args.current_programdata_lamports
    if old_balance is None:
        old_balance = rent(args.current_programdata_bytes)
    target = max(args.current_programdata_bytes, len(elf) + 45)
    extension = max(0, rent(target) - old_balance)
    buffer = rent(len(elf) + 37)
    fixed = {}
    for account in idl["accounts"]:
        if not account["name"].startswith("Stage1") and account["name"] not in {"Climb", "ClimbVersionIndex"}:
            continue
        try:
            size = 8 + size_of(account["type"], definitions)
        except (ValueError, KeyError):
            if account["name"] == "Stage1Boost":
                # Program InitSpace reserves max_len(16) hill public keys.
                size = 8 + 32*4 + 8*2 + 1 + 4 + 16*32 + 1
            elif account['name'] == 'Stage1SettlementCursor':
                # InitSpace reserves 26 full carried hold entries once. A Vec
                # avoids an oversized SBF stack frame; allocation is bounded.
                size = 8 + sum(4 + 26*size_of(field['type']['vec'], definitions)
                               if field['name'] == 'carriedHolds' else size_of(field['type'], definitions)
                               for field in account['type']['fields'])
            else: continue
        fixed[account["name"]] = {"bytes": size, "lamports": rent(size)}
    claims = []
    for leaves in (10, 100, 1000):
        tail = (leaves + 7) // 8
        cash = fixed['Stage1ClaimSet']['bytes'] + tail
        dung = fixed['Stage1DungClaimSet']['bytes'] + tail
        claims.append({'leaves': leaves, 'cashBytes': cash, 'dungRoleBytes': dung,
                       'cashRentLamports': rent(cash), 'dungRoleRentLamports': rent(dung),
                       'oldCashTotalLamports': rent(393) + leaves * (rent(84) + rent(44)),
                       'oldDungRoleTotalLamports': rent(106) + leaves * (rent(84) + rent(44))})
    weekly = None
    if args.before_idl:
        before=json.loads(Path(args.before_idl).read_text())
        old_defs={v['name']:v['type'] for v in before.get('types',[])}
        old={a['name']:8+size_of(a['type'],old_defs) for a in before['accounts'] if a['name'] in ('Stage1WeekFunding','Stage1ClaimSet','Stage1DungClaimSet','Stage1DungMint')}
        n=10;old_tail=(n+7)//8+32*n+10*(n-1);new_tail=(n+7)//8
        rows=[]
        for name,count,tail_before,tail_after in [('Stage1WeekFunding',args.cash_assets,0,0),('Stage1ClaimSet',args.cash_assets,old_tail,new_tail),('Stage1DungClaimSet',2,old_tail,new_tail),('Stage1DungMint',1,0,0)]:
            before_bytes=old[name]+tail_before;after_bytes=fixed[name]['bytes']+tail_after
            rows.append({'account':name,'perHillWeek':count,'beforeBytesEach':before_bytes,'afterBytesEach':after_bytes,'beforeLamports':count*rent(before_bytes),'afterLamports':count*rent(after_bytes)})
        total_before=sum(row['beforeLamports'] for row in rows);total_after=sum(row['afterLamports'] for row in rows)
        weekly={'assumption':'10 leaves in each cash/role set; 8 claimed within four weeks and 2 never, evenly spread: no set fully closes; no weekly cadence change',
                'cashAssets':args.cash_assets,'rows':rows,'beforeLamports':total_before,'afterLamports':total_after,
                'annual10Hills':{'weeks':52,'beforeGrossLamports':total_before*520,'beforeNetLamports':total_before*520,'afterGrossLamports':total_after*520,'afterNetLamports':total_after*520},
                'yieldComparison':[{'backingSol':b,'weeklyYieldLamports':y,'tenPercentFeeLamports':y//10,'beforeRentOverYield':total_before/y,'afterRentOverYield':total_after/y,'afterRentOverFee':total_after/(y//10)} for b,y in [(10,14000000),(100,140000000)]],
                'notWeekly':[name for name in fixed if name.startswith('Stage1') and name not in {row['account'] for row in rows}]}
    n=10;tail=(n+7)//8
    automatic_rows=[]
    for name,count,extra,closes in [
        ('Stage1WeekFunding',args.cash_assets,0,'after its cash set closes; residual holds carried to permanent cursor; untouched skipped books close after skip'),
        ('Stage1ClaimSet',args.cash_assets,tail,'after automatic cash payment at finalization; empty sealed sets immediately'),
        ('Stage1DungClaimSet',2,tail,'after every leaf is paid, no earlier than 48 hours after role publication; empty sets immediately'),
        ('Stage1DungMint',1,0,'after both role sets close and all allocated units are minted')]:
        size=fixed[name]['bytes']+extra
        automatic_rows.append({'account':name,'perHillWeek':count,'bytesEach':size,'lamports':count*rent(size),'closes':closes})
    funding=automatic_rows[0]['lamports'];cash=automatic_rows[1]['lamports']
    dung=sum(row['lamports'] for row in automatic_rows[2:]);total=funding+cash+dung
    automatic={'assumptions':'10 leaves/set; one active week at a time; funding opens at week start; finalization 24h after close; keeper promptly pays cash then DUNG 48h after role publication; all records eventually close; no keeper outage, transaction fees or capital cost included',
        'rows':automatic_rows,'weeklyGrossLamports':total,'weeklyRefundLamports':total,
        'steadyState10Hills':{'fundingOnlyLamports':10*funding,'during24hGraceLamports':20*funding,
            'during48hDungWaitLamports':10*(funding+dung),'publicationTransientPeakLamports':10*(2*funding+cash+dung),
            'timeWeightedAverageLamports':10*(8*funding+2*dung)/7},
        'annual10Hills':{'weeks':52,'grossLamports':520*total,'refundedLamports':520*total,'netRentLamports':0,
            'round2UnclaimedTailNetLamports':520*(args.cash_assets*(rent(467)+rent(277))+2*rent(142)+rent(186))},
        'permanentCursorPerHillAsset':fixed['Stage1SettlementCursor'],
        'limits':'Keeper outages, withheld proofs, token account freezes or settlement pause can prolong deposits; no incomplete set closes and claims never expire. One-time cursor capital, other activity accounts and transaction fees are separate.'}
    print(json.dumps({"evidence": "finalized RPC rent quote (read-only)" if args.rpc else "offline mainnet standard-rent quote; excludes transaction fees and backing deposits",
                     "weeklyRent":weekly,
                     "automaticPayoutRent":automatic,
                     "binaryBytes": len(elf), "binarySha256": hashlib.sha256(elf).hexdigest(),
                     "currentProgramDataBytes": args.current_programdata_bytes,
                     "targetProgramDataBytes": target, "extensionBytes": target - args.current_programdata_bytes,
                     "extensionLamports": extension, "temporaryBufferLamports": buffer,
                     "peakAdditionalLamports": extension + buffer, "fixedAccounts": fixed,
                     "claimTrackingRentLamports": 0, "oldClaimTrackingRentLamports": rent(84) + rent(44),
                     "publishedClaimSets": claims}, indent=2))


if __name__ == "__main__":
    main()
