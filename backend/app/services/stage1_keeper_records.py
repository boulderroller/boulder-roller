"""Retained accounting witnesses for permissionlessly closed weekly records."""
from .stage1_keeper_worker import Blocked


def restore_cash_books(observed, jobs):
    books = dict(observed['books'])
    carried = observed.get('carried',{})
    for job in jobs:
        retained = job.get('funding_publication')
        if not retained or not retained.get('closed'):
            continue
        address, account = retained['address'],dict(retained['account'])
        if not retained['closed'].get('signature') or (address in books and not books[address].get('closed_source')):
            raise Blocked('funding_closure_witness_mismatch', {'week':job['week']})
        # A closed positive hold keeps its original age and proposal in the
        # permanent cursor. Once consumed, finalized retained plans prove the
        # transition to paid value or the Pool even after that entry is removed.
        for later in sorted(jobs,key=lambda j:j['week']):
            if later['week'] <= job['week'] or not later.get('allocation'):
                continue
            for index, op in enumerate(later.get('operations') or []):
                applied = later['state']=='complete' or later.get('operation_index',0)>index
                if not applied:
                    continue
                if op['kind']=='expire' and op['source']==address:
                    account['pool'] += sum(account['holds'])
                    account['holds'] = [0]*5
                elif op['kind']=='publish' and address in op.get('sources',[]):
                    account['holds'] = later['allocation']['holds'][address]
        if address in carried:
            hold = carried[address]
            if hold['holds'] != account['holds'] or hold['lineage'] != account['lineage'] or hold['pool'] != account['pool']:
                raise Blocked('carried_hold_mismatch', {'week':job['week']})
            # Cursor carries settlement state, not the original book's lifetime
            # income counters. Synthetic inventory defaults must not erase them.
            account.update({k:hold[k] for k in ('holds','pool','lineage','revision','proposed','proposal_week','proposal_remaining','proposal_revision','proposal_snapshot') if k in hold})
        elif any(account['holds']):
            raise Blocked('carried_hold_missing', {'week':job['week']})
        books[address] = {**account,'closed_source':True,'lamports':0}
    if set(carried)-{j['funding_publication']['address'] for j in jobs if j.get('funding_publication') and j['funding_publication'].get('closed')}:
        raise Blocked('untracked_carried_hold', {})
    observed['books'] = books
    return books
