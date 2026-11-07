"""Independent IDL/Borsh verification of the TypeScript checkpoint decoder."""
import base64
import hashlib
import json

from solders.pubkey import Pubkey
from .stage1_keeper_paths import IDL
from .stage1_keeper_merkle import digest


def verify_accounts(accounts):
    idl=json.loads(IDL.read_text())
    definitions={a['name']:a['type'] for a in idl['accounts']+idl.get('types',[])}
    # The reviewed devnet ABI has one additional registration account. Reading
    # its layout does not authorize transactions or select a network.
    if any(a['type']=='Stage1TestPool' for a in accounts):
        devnet=json.loads(IDL.with_name('boulder_rollers.devnet.json').read_text())
        definitions.update({a['name']:a['type'] for a in devnet['accounts'] if a['name']=='Stage1TestPool'})
    for account in accounts:
        if account.get('omitted'):
            if set(account)-{'address','type','omitted','raw_digest','routing'}:
                raise ValueError('invalid erased account marker')
            continue
        erased=[];discarded=False
        if 'parts' in account:
            parts=account['parts']
            if digest([{k:v for k,v in p.items() if k not in ('data','erased','replacement','missing','discarded')} for p in parts])!=account['parts_digest']:
                raise ValueError('source span commitment mismatch')
            spans=[];end=0
            for part in parts:
                if part['offset']!=end or part['length']<0:
                    raise ValueError('source span gap or overlap')
                end+=part['length']
                if part.get('discarded'):
                    if part['path']!=['$padding'] or part['kind']!='bytes' or 'data' in part:
                        raise ValueError('invalid discarded source span')
                    discarded=True;spans.append(bytes(part['length']))
                elif part.get('erased'):
                    if any(str(p).startswith('$') for p in part['path']) or part['kind'] not in ('publicKey','i64','u64','u128','string','u8array'):
                        raise ValueError('invalid erased source span')
                    spans.append(bytes(part['length']));erased.append(part)
                else:
                    data=base64.b64decode(part['data'],validate=True)
                    if len(data)!=part['length'] or hashlib.sha256(data).hexdigest()!=part['digest']:
                        raise ValueError('surviving source span commitment mismatch')
                    spans.append(data)
            raw=b''.join(spans)
        else:
            raw=base64.b64decode(account['raw'],validate=True)
        if not erased and not discarded and hashlib.sha256(raw).hexdigest()!=account['raw_digest']:
            raise ValueError('source account commitment mismatch')
        name=account['type']
        if raw[:8]!=hashlib.sha256(('account:'+name).encode()).digest()[:8]:
            raise ValueError('source account discriminator mismatch')
        offset=8
        expected=[dict(path=['$discriminator'],kind='bytes',offset=0,length=8)]
        def take(n,path,kind):
            nonlocal offset
            if offset+n>len(raw):
                raise ValueError('truncated source account')
            expected.append(dict(path=path,kind=kind,offset=offset,length=n))
            result=raw[offset:offset+n];offset+=n
            return result
        def read(t,path):
            if isinstance(t,str):
                if t=='publicKey':
                    return str(Pubkey(take(32,path,t)))
                if t=='bool':
                    byte=take(1,path,t)[0]
                    if byte not in (0,1):
                        raise ValueError('invalid Borsh bool')
                    return bool(byte)
                if t in ('string','bytes'):
                    data=take(int.from_bytes(take(4,path+['$length'],'u32'),'little'),path,t)
                    return data.decode() if t=='string' else list(data)
                if t[0] in ('u','i') and t[1:].isdigit():
                    width=int(t[1:]);number=int.from_bytes(take(width//8,path,t),'little',signed=t[0]=='i')
                    return str(number) if width>=64 else number
                raise ValueError('unsupported Borsh scalar')
            if 'array' in t:
                if t['array'][0]=='u8':
                    return list(take(t['array'][1],path,'u8array'))
                return [read(t['array'][0],path+[str(i)]) for i in range(t['array'][1])]
            if 'vec' in t:
                n=int.from_bytes(take(4,path+['$length'],'u32'),'little')
                if n>65536:
                    raise ValueError('unbounded source vector')
                return [read(t['vec'],path+[str(i)]) for i in range(n)]
            if 'option' in t:
                tag=take(1,path+['$option'],'u8')[0]
                if tag not in (0,1):
                    raise ValueError('invalid Borsh option')
                return read(t['option'],path) if tag else None
            if 'defined' in t:
                return read(definitions[t['defined']],path)
            if t['kind']=='struct':
                return {f['name']:read(f['type'],path+[f['name']]) for f in t['fields']}
            if t['kind']=='enum':
                variant=t['variants'][take(1,path+['$variant'],'u8')[0]]
                name=variant['name'];name=name[0].lower()+name[1:]
                if variant.get('fields'):
                    raise ValueError('unsupported payload enum')
                return {name:{}}
            raise ValueError('unsupported Borsh type')
        definition=definitions[name]
        legacy_legend=name=='LocalLegend' and len(raw)==122
        if legacy_legend:
            definition={**definition,'fields':[f for f in definition['fields'] if f['name']!='isBootstrap']}
        decoded=read(definition,[])
        if offset<len(raw):
            expected.append(dict(path=['$padding'],kind='bytes',offset=offset,length=len(raw)-offset))
        if 'parts' in account and [{k:p[k] for k in ('path','kind','offset','length')} for p in account['parts']]!=expected:
            raise ValueError('independent source span layout disagrees')
        if legacy_legend:
            decoded['isBootstrap']=decoded['isActive'] and decoded['electionPeriod']=='0' and decoded['completionsAtElection']==0
        for part in erased:
            parent=decoded
            for key in part['path'][:-1]:
                parent=parent[int(key)] if isinstance(parent,list) else parent[key]
            key=part['path'][-1]
            if isinstance(parent,list):
                parent[int(key)]=part.get('replacement')
            elif part.get('missing'):
                parent.pop(key,None)
            else:
                parent[key]=part.get('replacement')
        if decoded!=account['fields']:
            raise ValueError('independent account replay disagrees')
