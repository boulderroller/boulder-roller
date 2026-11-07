import {useState,type ReactNode} from 'react';
export function AuthRuntimeProvider({children}:{children:ReactNode}){return <>{children}</>;}
export function AuthRuntimeBoundary({fallback,children}:{fallback?:ReactNode;children?:ReactNode;[key:string]:unknown}){return <>{fallback??children}</>;}
export function useAuthRuntime(){const [status,setStatus]=useState<'idle'|'failed'>('idle');return {ready:false,status,error:status==='failed'?'Sign-in failed to load.':null,ensureRuntime:()=>setStatus('failed'),retryRuntime:()=>setStatus('failed')};}
export function useDeferredWalletTransactionSigner(){return {setSignerRef:()=>{},signerEnabled:false,signPreparedTransaction:async()=>{throw Error('Signing is unavailable in this retained workshop.');}};}
export function WalletTransactionSignerBridge(){return null;}
