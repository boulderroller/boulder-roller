import BN from 'bn.js';
import {createHash} from 'crypto';
import {PublicKey} from '@solana/web3.js';

export const digest=(...parts:Uint8Array[])=>createHash('sha256').update(Buffer.concat(parts)).digest();
export const le64=(value:BN)=>value.toTwos(64).toArrayLike(Buffer,'le',8);
export function cashClaimTerms(book:any,newHolds:BN[],releaseCommitment:Uint8Array){
  return {cap:book.cap,frozenAt:book.frozenAt,auditHash:[...digest(Buffer.from('BR-stage1-v2:cash-audit\0'),
    Buffer.from(book.snapshot),Buffer.from(book.lineage),releaseCommitment,Buffer.from(book.boostCommitment),...newHolds.map(le64))]};
}
export function cashTermsCommitment(address:PublicKey,terms:any){
  return digest(Buffer.from('BR-stage1-v2:claim-terms\0'),address.toBuffer(),le64(terms.cap),le64(terms.frozenAt),Buffer.from(terms.auditHash));
}
