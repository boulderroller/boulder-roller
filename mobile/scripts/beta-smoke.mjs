#!/usr/bin/env node

import { spawnSync } from 'node:child_process';

const checks = [
  { label: 'lint', command: 'npm', args: ['run', 'lint'] },
  { label: 'typecheck', command: 'npm', args: ['run', 'typecheck'] },
  { label: 'tests', command: 'npm', args: ['test', '--', '--runInBand'] },
];

const manualPass = [
  'Fresh install or clear app data; app opens to Login or Home.',
  'Sign in; Home, Record, Climbs, Profile tabs load.',
  'Home chips switch Following, You, Global; You keeps local rides.',
  'Search opens ride, rider, climb, and proof targets.',
  'Record a short GPS ride; stop; Post Ride shows saved/upload/checking state.',
  'Ride Detail supports kudos, comment, share, privacy, and proof target.',
  'Notifications open their target and mark read.',
  'Profile settings open Privacy, Notifications, Reports, Pairing, Wallet.',
  'Physical iPhone: pair BLE sensor; record; confirm sensor values and FIT export evidence.',
];

function runCheck(check) {
  console.log(`\n> ${check.label}`);
  const result = spawnSync(check.command, check.args, {
    stdio: 'inherit',
    shell: process.platform === 'win32',
  });
  if (result.status !== 0) {
    console.error(`\n${check.label} failed.`);
    process.exit(result.status ?? 1);
  }
}

for (const check of checks) {
  runCheck(check);
}

console.log('\nStatic gates passed.');
console.log('\nManual beta pass:');
manualPass.forEach((item, index) => {
  console.log(`${index + 1}. ${item}`);
});
