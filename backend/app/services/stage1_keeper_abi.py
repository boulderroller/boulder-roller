"""Pinned composed-release layouts and immutable cash publication witnesses."""
import hashlib
import struct

from solders.pubkey import Pubkey


LAYOUTS = {
    'Stage1HillBond': {'city': 9},
    'Stage1AssetConfig': {'city': 9, 'mint': 41},
    'Stage1PledgeLot': {'mint': 105},
    'Stage1WeekFunding': {'hill': 40, 'mint': 104},
    'Stage1SettlementCursor': {'hill': 40, 'mint': 104},
    'Stage1ClaimSet': {'mint': 104, 'paid': 260, 'claimedCount': 268, '$header': 275},
    'Stage1DungMint': {'hill': 40, 'mint': 72},
    'Stage1DungClaimSet': {'dung': 8, 'paid': 85, 'claimedCount': 93, '$header': 140},
    'Stage1Boost': {'city': 8, 'mint': 40},
    'Stage1BoostHill': {'boost': 8, 'hill': 40},
    'Stage1Recipient': {'person': 8},
}


def validate_layouts(idl):
    definitions = {v['name']: v['type'] for v in idl.get('types', []) + idl['accounts']}
    def size(value):
        if isinstance(value, str):
            return {'bool': 1, 'u8': 1, 'i8': 1, 'u16': 2, 'i16': 2,
                    'u32': 4, 'i32': 4, 'u64': 8, 'i64': 8, 'u128': 16, 'i128': 16,
                    'publicKey': 32}[value]
        if 'array' in value:
            return size(value['array'][0]) * value['array'][1]
        if 'defined' in value:
            return sum(size(f['type']) for f in definitions[value['defined']]['fields'])
        raise KeyError('variable size')
    for name, expected in LAYOUTS.items():
        found, offset = {}, 8
        for field in definitions[name]['fields']:
            found[field['name']] = offset
            try:
                offset += size(field['type'])
            except KeyError:
                break
        else:
            found['$header'] = offset
        if any(found.get(field) != position for field, position in expected.items()):
            raise ValueError(f'unsupported composed Stage 1 layout: {name}')


def cash_terms(address, event, claim_set):
    """Only an actual publication event supplies its release commitment."""
    terms, audit = event['terms'], event['audit']
    fields = ('snapshot', 'source_lineage', 'release_commitment', 'boost_commitment')
    def raw(value):
        return bytes.fromhex(value) if isinstance(value, str) else bytes(value)
    pieces = [raw(audit[name]) for name in fields]
    if any(len(p) != 32 for p in pieces):
        raise ValueError('invalid cash publication audit')
    audit_hash = hashlib.sha256(b'BR-stage1-v2:cash-audit\0' + b''.join(pieces)
                               + struct.pack('<5Q', *audit['new_holds'])).digest()
    metadata = hashlib.sha256(b'BR-stage1-v2:claim-terms\0' + bytes(Pubkey.from_string(address))
                             + struct.pack('<Qq', terms['cap'], terms['frozen_at']) + audit_hash).digest()
    if (raw(terms['audit_hash']) != audit_hash or raw(claim_set['metadata_hash']) != metadata
        or event['claim_set'] != address or raw(event['root']) != raw(claim_set['root'])
        or event['total'] != claim_set['total'] or event['leaf_count'] != claim_set['leaf_count']):
        raise ValueError('cash publication event does not match sealed set')
    return {'cap': terms['cap'], 'frozen_at': terms['frozen_at'], 'audit_hash': audit_hash.hex()}
