import {
  formatAtomic,
  formatCount,
  formatDuration,
  formatEpoch,
  formatElevationTenths,
  humanizeEventName,
  humanizeLabel,
  looksLikePubkey,
  shortenAddress,
} from '@/lib/format';
import type { ExplorerEvent, TransactionInstruction, TransactionResponse } from '@/types';

export type ExplorerReference =
  | { kind: 'climb'; label: string; value: string }
  | { kind: 'account'; label: string; value: string }
  | { kind: 'text'; label: string; value: string };

export type ExplorerNarrative = {
  title: string;
  detail: string;
  highlights: string[];
};

function readString(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  const text = String(value).trim();
  return text ? text : null;
}

function readBoolean(value: unknown): boolean | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'boolean') return value;
  const text = String(value).trim().toLowerCase();
  if (text === 'true') return true;
  if (text === 'false') return false;
  return null;
}

function vaultIdFromRecord(record: Record<string, unknown>): string | null {
  const id = readString(record.vault_id ?? record.vaultId ?? record.id);
  if (!id || !/^\d+$/.test(id)) return null;
  return id;
}

function renderVaultLabel(record: Record<string, unknown>): string | null {
  const id = vaultIdFromRecord(record);
  return id ? `Climb #${id}` : null;
}

function renderAccount(value: unknown): string | null {
  const account = readString(value);
  if (!account || !looksLikePubkey(account)) return null;
  return shortenAddress(account);
}

function renderCount(value: unknown, label: string): string | null {
  const count = formatCount(value);
  return count === '—' ? null : `${count} ${label}`;
}

function renderEpoch(value: unknown): string | null {
  const epoch = formatEpoch(value);
  return epoch === '—' ? null : epoch;
}

function renderWeek(value: unknown): string | null {
  const week = formatCount(value);
  return week === '—' ? null : `Week ${week}`;
}

function renderAmount(value: unknown, symbol: string): string | null {
  const amount = formatAtomic(value, symbol);
  return amount === '—' ? null : amount;
}

function renderDurationValue(value: unknown): string | null {
  const duration = formatDuration(value);
  return duration === '—' ? null : duration;
}

function renderElevation(value: unknown): string | null {
  const elevation = formatElevationTenths(value);
  return elevation === '—' ? null : elevation;
}

function renderPaymentMethod(value: unknown): string | null {
  const method = readString(value);
  return method ? humanizeLabel(method) : null;
}

function narrative(title: string, detail: string, highlights: Array<string | null | false | undefined> = []): ExplorerNarrative {
  return {
    title,
    detail,
    highlights: highlights.filter((value): value is string => Boolean(value)),
  };
}

function pushUniqueReference(target: ExplorerReference[], next: ExplorerReference | null) {
  if (!next) return;
  if (target.some((current) => current.kind === next.kind && current.label === next.label && current.value === next.value)) {
    return;
  }
  target.push(next);
}

function vaultReferenceFromRecord(record: Record<string, unknown>): ExplorerReference | null {
  const id = readString(record.climb_id);
  if (!id) return null;
  return { kind: 'climb', label: 'Climb', value: id };
}

function accountReference(label: string, value: unknown): ExplorerReference | null {
  const text = readString(value);
  if (!text || !looksLikePubkey(text)) return null;
  return { kind: 'account', label, value: text };
}

export function extractEventReferences(event: ExplorerEvent): ExplorerReference[] {
  const refs: ExplorerReference[] = [];
  const fields = event.fields ?? {};

  pushUniqueReference(refs, vaultReferenceFromRecord({ climb_id: event.climb_id }));

  const accountCandidates: Array<[string, unknown]> = [
    ['Creator', fields.creator],
    ['Created by', fields.minter],
    ['Recipient', fields.recipient],
    ['Holder', fields.holder],
    ['Rider', fields.rider ?? fields.user],
    ['Staker', fields.staker],
    ['Legend', fields.legend],
    ['Owner', fields.owner_pubkey ?? fields.owner],
    ['Runner-up', fields.runner_up ?? fields.runnerUp],
  ];

  for (const [label, value] of accountCandidates) {
    pushUniqueReference(refs, accountReference(label, value));
  }

  const week = readString(fields.settlement_week ?? fields.settlementWeek ?? fields.epoch);
  if (week && /^\d+$/.test(week)) {
    pushUniqueReference(refs, { kind: 'text', label: 'Week', value: week });
  }

  return refs.slice(0, 3);
}

export function describeExplorerEvent(event: ExplorerEvent): ExplorerNarrative {
  const fields = event.fields ?? {};
  const vault = renderVaultLabel(fields);

  // A decoded Vault number alone cannot attest a canon Climb creation.
  if (event.event_name === 'VaultCreated' && !event.climb_id) {
    return narrative('', '', []);
  }

  switch (event.event_name) {
    case 'VaultCreated': {
      const minter = renderAccount(fields.minter);
      const paymentMethod = renderPaymentMethod(fields.paymentMethod ?? fields.payment_method);
      return narrative(
        vault ? `${vault} was created` : 'A new climb was created',
        [
          minter ? `${minter} created a new climb` : 'A new climb was created',
          paymentMethod ? `using ${paymentMethod}` : null,
          '.',
        ]
          .filter(Boolean)
          .join(' '),
        [renderElevation(fields.vert_m ?? fields.vertM), paymentMethod ? `Payment ${paymentMethod}` : null]
      );
    }

    case 'VaultCompleted':
    case 'VaultCompletedV2':
    case 'ClimbCompleted':
    case 'ClimbCompletedV2': {
      const rider = renderAccount(fields.rider ?? fields.user);
      const time = renderDurationValue(fields.time_s ?? fields.timeS);
      const tribute = renderAmount(fields.cal_tributed ?? fields.calTributed, 'CAL');
      const tookKom = readBoolean(fields.is_new_kom ?? fields.isNewKom);
      const evidenceVersion = readString(fields.evidence_version ?? fields.evidenceVersion);
      const vaultName = vault ?? 'a climb';
      return narrative(
        vault ? `Completed ${vault}${time ? ` in ${time}` : ''}` : 'Climb completed',
        [
          rider ? `${rider} completed ${vaultName}${time ? ` in ${time}` : ''}` : `A rider completed ${vaultName}${time ? ` in ${time}` : ''}`,
          tribute ? `and tributed ${tribute}` : null,
          tookKom ? '— new KOM!' : '.',
        ]
          .filter(Boolean)
          .join(' '),
        [time, tribute, tookKom ? 'New KOM' : null, evidenceVersion ? `Evidence V${evidenceVersion}` : null]
      );
    }

    case 'ClimbCompletionFlowAssigned':
    case 'ClimbCompletionFlowAssignedV2': {
      const tribute = renderAmount(fields.cal_tributed ?? fields.calTributed, 'CAL');
      const settlementWeek = readString(
        fields.credited_settlement_week ?? fields.creditedSettlementWeek
      );
      const week = settlementWeek ? `Settlement Week ${settlementWeek}` : null;
      const evidenceVersion = readString(fields.evidence_version ?? fields.evidenceVersion);
      return narrative(
        vault ? `Settlement flow assigned for ${vault}` : 'Settlement flow assigned',
        [
          tribute ?? 'The completion tribute',
          'entered',
          week ?? 'its credited Settlement Week',
          vault ? `for ${vault}.` : '.',
        ]
          .filter(Boolean)
          .join(' '),
        [tribute, week, evidenceVersion ? `Evidence V${evidenceVersion}` : null]
      );
    }

    case 'CalStaked': {
      const staker = renderAccount(fields.staker);
      const amount = renderAmount(fields.amount, 'CAL');
      const lpMinted = renderAmount(fields.lpMinted ?? fields.lp_minted, 'vLP');
      return narrative(
        vault ? `${vault} received stake` : 'CAL was staked',
        [
          staker ? `${staker} staked ${amount ?? 'CAL'}` : amount ? `${amount} was staked` : 'A stake was recorded',
          vault ? `into ${vault}` : '',
          '.',
        ]
          .filter(Boolean)
          .join(' '),
        [amount, lpMinted ? `LP ${lpMinted}` : null]
      );
    }

    case 'CalUnstaked': {
      const staker = renderAccount(fields.staker);
      const returned = renderAmount(fields.calReturned ?? fields.cal_returned, 'CAL');
      const lpBurned = renderAmount(fields.lpBurned ?? fields.lp_burned, 'vLP');
      return narrative(
        vault ? `${vault} stake was withdrawn` : 'CAL was unstaked',
        [
          staker ? `${staker} withdrew ${returned ?? 'CAL'}` : returned ? `${returned} was withdrawn` : 'A stake position was unwound',
          vault ? `from ${vault}` : '',
          '.',
        ]
          .filter(Boolean)
          .join(' '),
        [returned, lpBurned ? `LP burned ${lpBurned}` : null]
      );
    }

    case 'VaultAllocClaimed': {
      const calAmount = renderAmount(fields.calAmount ?? fields.cal_amount, 'CAL');
      const dungConverted = renderAmount(fields.dungConverted ?? fields.dung_converted, 'DUNG');
      const epoch = renderEpoch(fields.epoch);
      const batchId = readString(fields.batchId ?? fields.batch_id);
      return narrative(
        vault ? `${vault} claimed tribute allocation` : 'A climb allocation was claimed',
        [
          vault ?? 'A climb',
          'claimed',
          calAmount ?? 'tribute',
          batchId ? `from batch ${batchId}` : '',
          dungConverted ? `and converted it into ${dungConverted}` : '',
          epoch ? `for ${epoch}` : '',
          '.',
        ]
          .filter(Boolean)
          .join(' '),
        [calAmount, dungConverted, epoch]
      );
    }

    case 'EpochRewardsDistributed': {
      const total = renderAmount(fields.totalDistributed ?? fields.total_distributed, 'DUNG');
      const week = renderWeek(fields.settlementWeek ?? fields.settlement_week ?? fields.epoch);
      return narrative(
        vault ? `${vault} settlement` : 'Weekly settlement',
        `${total ?? 'DUNG'} distributed${week ? ` in ${week}` : ''}.`,
        [
          total,
          renderAmount(fields.stakerDistributed ?? fields.staker_distributed, 'DUNG')
            ? `Stakers ${renderAmount(fields.stakerDistributed ?? fields.staker_distributed, 'DUNG')}`
            : null,
          renderAmount(fields.localLegendDistributed ?? fields.local_legend_distributed, 'DUNG')
            ? `Local Legend ${renderAmount(fields.localLegendDistributed ?? fields.local_legend_distributed, 'DUNG')}`
            : null,
          week,
        ]
      );
    }

    case 'StakerRemainderPolicyApplied': {
      const amount = renderAmount(
        fields.legacyCarryReallocated ?? fields.legacy_carry_reallocated,
        'DUNG'
      );
      const week = renderWeek(
        fields.settlementWeek ?? fields.settlement_week ?? fields.epoch
      );
      return narrative(
        'Staker balance sweep',
        `${amount ?? 'The prior staker balance'} moved from Prior staker balance to Leaderboard pool${week ? ` in ${week}` : ''}.`,
        [amount, week]
      );
    }

    case 'VaultActivated': {
      const seeded = renderCount(fields.seedCompletionsWritten ?? fields.seed_completions_written, 'seeded completions');
      const leaderboardSeeded = readBoolean(fields.leaderboardSeeded ?? fields.leaderboard_seeded);
      return narrative(
        vault ? `${vault} is now live` : 'Climb economics were activated',
        [
          vault ?? 'This climb',
          'crossed the activation boundary and can now emit live economic effects.',
        ].join(' '),
        [seeded, leaderboardSeeded ? 'Leaderboard seeded' : null]
      );
    }

    case 'DungMinted': {
      const amount = renderAmount(fields.amount, 'DUNG');
      const recipient = renderAccount(fields.recipient);
      const allocation = renderAmount(fields.allocation, 'DUNG');
      return narrative(
        amount ? `${amount} minted` : 'DUNG was minted',
        [
          amount ? `${amount} was minted` : 'DUNG was minted',
          recipient ? `to ${recipient}` : '',
          '.',
        ]
          .filter(Boolean)
          .join(' '),
        [allocation ? `Allocation ${allocation}` : null]
      );
    }

    case 'LocalLegendElected': {
      const legend = renderAccount(fields.holder ?? fields.legend);
      const runnerUp = renderAccount(fields.runner_up ?? fields.runnerUp);
      return narrative(
        vault ? `${vault} rotated Local Legend` : 'A Local Legend was elected',
        [
          legend ? `${legend} won the Local Legend seat` : 'A new Local Legend was elected',
          runnerUp ? `over ${runnerUp}` : '',
          '.',
        ]
          .filter(Boolean)
          .join(' '),
        [renderEpoch(fields.termStartEpoch ?? fields.term_start_epoch), renderEpoch(fields.termEndEpoch ?? fields.term_end_epoch)]
      );
    }

    case 'CalTributed': {
      const amount = renderAmount(fields.amount, 'CAL');
      return narrative(
        vault ? `CAL tributed to ${vault}` : 'CAL tributed to a climb',
        [
          amount ?? 'CAL',
          'was tributed to',
          vault ?? 'a climb',
          'as ride effort allocation.',
        ].join(' '),
        [amount]
      );
    }

    case 'DungBurned': {
      const amount = renderAmount(fields.amount, 'DUNG');
      return narrative(
        amount ? `${amount} burned` : 'DUNG burned',
        `${amount ?? 'DUNG'} was permanently burned.`,
        [amount]
      );
    }

    case 'BeetleCardUpgraded': {
      const rider = renderAccount(fields.user ?? fields.owner);
      const level = formatCount(fields.level ?? fields.new_level ?? fields.newLevel);
      return narrative(
        'BeetleCard upgraded',
        [
          rider ?? 'A rider',
          'upgraded their BeetleCard to level',
          `${level}.`,
        ].join(' '),
        [level !== '—' ? `Level ${level}` : null]
      );
    }

    case 'KomUpdated': {
      const rider = renderAccount(fields.user ?? fields.holder ?? fields.new_holder ?? fields.newHolder);
      const time = renderDurationValue(fields.time_s ?? fields.timeS ?? fields.new_time_s ?? fields.newTimeS);
      return narrative(
        vault ? `New KOM on ${vault}` : 'New KOM recorded',
        [
          rider ?? 'A rider',
          'set a new fastest time',
          time ? `of ${time}` : '',
          vault ? `on ${vault}!` : '!',
        ]
          .filter(Boolean)
          .join(' '),
        [time, rider]
      );
    }

    case 'LeaderboardUpdated': {
      const entries = renderCount(fields.entries ?? fields.total_entries ?? fields.totalEntries, 'entries');
      return narrative(
        vault ? `Leaderboard reshuffled on ${vault}` : 'Leaderboard reshuffled',
        [
          'A new time was posted, updating the top 10',
          vault ? `for ${vault}.` : '.',
        ].join(' '),
        [entries]
      );
    }

    default:
      return narrative(
        humanizeEventName(event.event_name),
        'Indexed protocol event. Review the decoded fields for the exact on-chain payload.'
      );
  }
}

function instructionAccountReference(
  label: string,
  value: string | { pubkey: string }
): ExplorerReference | null {
  const allowedLabels = new Set(['creator', 'minter', 'user', 'recipient', 'holder', 'owner']);
  if (!allowedLabels.has(label)) return null;

  const pubkey = typeof value === 'string' ? value : value.pubkey;
  if (!looksLikePubkey(pubkey)) return null;
  const labelMap: Record<string, string> = {
    creator: 'Creator',
    minter: 'Created by',
    user: 'Rider',
    recipient: 'Recipient',
    holder: 'Holder',
    owner: 'Owner',
  };
  const normalized = labelMap[label] ?? humanizeLabel(label);
  return { kind: 'account', label: normalized, value: pubkey };
}

export function extractTransactionOverview(data: TransactionResponse): ExplorerReference[] {
  const refs: ExplorerReference[] = [];
  const firstEvent = data.events[0];
  const firstInstruction = data.instructions[0];

  if (firstEvent) {
    for (const ref of extractEventReferences(firstEvent)) {
      pushUniqueReference(refs, ref);
    }
  }

  if (firstInstruction) {
    pushUniqueReference(refs, vaultReferenceFromRecord(firstInstruction.args));

    const accountEntries = Object.entries(firstInstruction.accounts);
    for (const [label, value] of accountEntries) {
      pushUniqueReference(refs, instructionAccountReference(label, value));
    }
  }

  return refs.slice(0, 4);
}

export function primaryInstruction(data: TransactionResponse): TransactionInstruction | null {
  return data.instructions[0] ?? null;
}

export function summarizeTransaction(data: TransactionResponse): ExplorerNarrative {
  const firstEvent = data.events[0];
  if (firstEvent) {
    return describeExplorerEvent(firstEvent);
  }

  const firstInstruction = data.instructions[0];
  if (firstInstruction) {
    return narrative(
      `${humanizeLabel(firstInstruction.name)} executed`,
      `This signature contains ${formatCount(data.instructions.length)} indexed Boulder Roller instruction${data.instructions.length === 1 ? '' : 's'}, but no explorer event narrative was emitted for it yet.`
    );
  }

  return narrative(
    'Indexed Boulder Roller transaction',
    'This signature is present in the read model, but no decoded explorer summary was available.'
  );
}
