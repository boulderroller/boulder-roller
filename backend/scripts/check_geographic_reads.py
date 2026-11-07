"""Static current-consumer census; does NOT establish READ-01/02 or lfsu0."""
import ast
from pathlib import Path

# Explicit census: a new query, table, or consumer needs classification.
CONSUMERS={
 'routes/climbs.py': {'canon_climbs':6,'indexed_climbs':4,'indexed_vaults':9,'climb_vault':2,'indexed_leaderboards':1,'vault_completions':1},
 'repositories/canon.py': {'canon_climbs':3,'canon_corridor_cells':2},
 'services/canon_registration_artifact.py': {},
}

class BoundaryViolation(AssertionError): pass


def calls(node):
    result=[]
    while isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
        try: args=[ast.literal_eval(a) for a in node.args]
        except (ValueError,TypeError): args=[]
        result.append((node.func.attr,args))
        node=node.func.value
    return result


def identity_only_lookup(relative, outer, parents):
    """Only the bounded existence probe may see identities of candidate rows."""
    if relative != 'repositories/canon.py': return False
    parent=outer
    while parent in parents and not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
        parent=parents[parent]
    if not isinstance(parent, ast.AsyncFunctionDef) or parent.name!='_load_existing_registry_ids': return False
    chain=[];node=outer
    while isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
        chain.append(node);node=node.func.value
    if [n.func.attr for n in chain] != ['execute','in_','select','table']: return False
    execute,bounded,selected,table=chain
    return (not any(n.keywords for n in chain) and not execute.args
            and len(selected.args)==1 and ast.literal_eval(selected.args[0])=='id'
            and len(bounded.args)==2 and ast.literal_eval(bounded.args[0])=='id'
            and ast.unparse(bounded.args[1])=='list(batch)')


def check_source(relative, source):
    tree=ast.parse(source);parents={child:node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    counts={}
    for node in ast.walk(tree):
        if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Attribute) or node.func.attr not in ('from_','table'): continue
        if not node.args or not isinstance(node.args[0],ast.Constant): raise BoundaryViolation('Dynamic table requires classification')
        table=node.args[0].value;counts[table]=counts.get(table,0)+1
        if table not in CONSUMERS[relative]: raise BoundaryViolation('Unclassified/candidate/atlas table: '+str(table))
        outer=node
        while outer in parents and isinstance(parents[outer],(ast.Call,ast.Attribute)): outer=parents[outer]
        chain=calls(outer)
        if table=='canon_climbs':
            accepted=('eq',['status','ratified']) in chain
            historical=('in_',['status',['ratified','retired']]) in chain
            if not (accepted or historical or identity_only_lookup(relative,outer,parents)):
                raise BoundaryViolation('Missing ratified registry filter')
        if table=='climb_vault':
            # Old /segments aliases have independent legacy projections. They must
            # remain behind the explicit alias guard, never enter /climbs reads.
            parent=node;guarded=False
            while parent in parents:
                parent=parents[parent]
                if isinstance(parent,ast.If) and '_is_legacy_segment_request' in ast.unparse(parent.test): guarded=True
            if not guarded: raise BoundaryViolation('Legacy geography outside alias guard')
    if counts!=CONSUMERS[relative]: raise BoundaryViolation(f'Consumer census changed: {relative}: {counts}')
    if relative=='services/canon_registration_artifact.py':
        guards=[n for n in ast.walk(tree) if isinstance(n,ast.If) and ast.unparse(n.test)=="status != 'ratified'"]
        if len(guards)!=1 or not any(isinstance(n,ast.Raise) for n in guards[0].body): raise BoundaryViolation('Registration must reject non-ratified rows')
    return counts

if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]/'app'
    for name in CONSUMERS: print(name,check_source(name,(root/name).read_text()))
