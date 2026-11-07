import {
  AlertTriangle,
  Bell,
  Check,
  Coins,
  Crown,
  MessageCircle,
  Shield,
  ThumbsUp,
  TrendingDown,
  Trophy,
  Users,
} from 'lucide-react';
import type { PushKind } from '../../lib/notificationLedger';

/** One 16px stroke glyph per push kind; colour comes from the row's state. */
export function PushGlyph({ kind, size = 16 }: { kind: PushKind; size?: number }) {
  const props = { size, 'aria-hidden': true as const };
  switch (kind) {
    case 'entry':
      return <Trophy {...props} />;
    case 'seat-lost':
      return <TrendingDown {...props} />;
    case 'legend':
      return <Crown {...props} />;
    case 'money':
      return <Coins {...props} />;
    case 'ride':
      return <Check {...props} />;
    case 'attention':
      return <AlertTriangle {...props} />;
    case 'kudos':
      return <ThumbsUp {...props} />;
    case 'comment':
      return <MessageCircle {...props} />;
    case 'follow':
      return <Users {...props} />;
    case 'account':
      return <Shield {...props} />;
    default:
      return <Bell {...props} />;
  }
}
