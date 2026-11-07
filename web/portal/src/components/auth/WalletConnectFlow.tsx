import WalletConnect from './WalletConnect';
import type { AuthTransactionMethod, AuthTransactionStage } from '../../lib/authTransaction';
import { WalletRuntimeProvider } from './WalletRuntimeProvider';

interface WalletConnectFlowProps {
  authTransactionId?: string;
  authTransactionMethod?: AuthTransactionMethod;
  authTransactionStage?: AuthTransactionStage;
  onSuccess: () => void;
  onBack: () => void;
}

export default function WalletConnectFlow(props: WalletConnectFlowProps) {
  return (
    <WalletRuntimeProvider>
      <WalletConnect {...props} />
    </WalletRuntimeProvider>
  );
}
