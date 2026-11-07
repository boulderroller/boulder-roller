import { useState } from 'react';
import { BeetleButton } from '../ui/beetle-button';
import { Copy, Check, CheckCircle2, Clock3 } from 'lucide-react';
import { toast } from 'sonner';
import { formatInteger } from '../../lib/formatters';
import {
  ResponsiveModal,
  ResponsiveModalHeader,
  ResponsiveModalTitle,
  ResponsiveModalDescription,
  ResponsiveModalBody,
  ResponsiveModalFooter,
} from '../ui/responsive-modal';

interface InvitedFriend {
  username: string;
  status: 'joined' | 'pending';
  date: string;
}

interface InviteFriendModalProps {
  inviteCode: string;
  invitesRemaining: number;
  invitedFriends: InvitedFriend[];
  onClose: () => void;
}

export default function InviteFriendModal({ inviteCode, invitesRemaining, invitedFriends, onClose }: InviteFriendModalProps) {
  const [copiedCode, setCopiedCode] = useState(false);
  const [copiedLink, setCopiedLink] = useState(false);

  const inviteLink = `${window.location.origin}/invite/${inviteCode}`;

  const handleCopyCode = async () => {
    await navigator.clipboard.writeText(inviteCode);
    setCopiedCode(true);
    toast.success('Code copied! 📋');
    setTimeout(() => setCopiedCode(false), 2000);
  };

  const handleCopyLink = async () => {
    await navigator.clipboard.writeText(inviteLink);
    setCopiedLink(true);
    toast.success('Link copied! 🔗');
    setTimeout(() => setCopiedLink(false), 2000);
  };

  return (
    <ResponsiveModal open={true} onOpenChange={(open) => { if (!open) onClose(); }}>
      <ResponsiveModalHeader>
        <ResponsiveModalTitle className="invite-friend-modal-title">
          🎟️ Invite Friends
        </ResponsiveModalTitle>
        <ResponsiveModalDescription className="sr-only">
          Copy an invite code or link and review recent invite status.
        </ResponsiveModalDescription>
      </ResponsiveModalHeader>

      <ResponsiveModalBody className="invite-friend-modal-body">
        {/* Invite Stats */}
        <div className="invite-friend-modal-stats">
          <div className="invite-friend-modal-stats__row">
            <div className="invite-friend-modal-stat">
              <div className="invite-friend-modal-stat__value">
                {formatInteger(invitesRemaining)}
              </div>
              <div className="invite-friend-modal-label">
                Invites Remaining
              </div>
            </div>
            <div className="invite-friend-modal-stat invite-friend-modal-stat--right">
              <div className="invite-friend-modal-stat__value invite-friend-modal-stat__value--secondary">
                {formatInteger(invitedFriends.length)}
              </div>
              <div className="invite-friend-modal-label">
                Friends Invited
              </div>
            </div>
          </div>
        </div>

        {/* Invite Code - HERO */}
        <div className="invite-friend-modal-code-section">
          <label className="invite-friend-modal-label invite-friend-modal-label--code">
            Your Invite Code
          </label>
          <div className="invite-friend-modal-code-card">
            <div className="invite-friend-modal-code" aria-label="Invite code">
              {inviteCode}
            </div>
          </div>
          <BeetleButton
            onClick={handleCopyCode}
            className="invite-friend-modal-action"
          >
            {copiedCode ? (
              <>
                <Check className="invite-friend-modal-action__icon" />
                <span>Copied!</span>
              </>
            ) : (
              <>
                <Copy className="invite-friend-modal-action__icon" />
                <span>Copy Code</span>
              </>
            )}
          </BeetleButton>
        </div>

        {/* Or Share Link */}
        <div className="invite-friend-modal-share">
          <label className="invite-friend-modal-label invite-friend-modal-label--share">
            Or Share Link
          </label>
          <div className="invite-friend-modal-share__row">
            <input
              type="text"
              value={inviteLink}
              readOnly
              className="invite-friend-modal-share__input"
            />
            <button
              type="button"
              onClick={handleCopyLink}
              className="invite-friend-modal-share__copy"
              aria-label={copiedLink ? 'Invite link copied' : 'Copy invite link'}
            >
              {copiedLink ? (
                <Check className="invite-friend-modal-share__icon" />
              ) : (
                <Copy className="invite-friend-modal-share__icon" />
              )}
            </button>
          </div>
        </div>

        {/* Divider */}
        <div className="invite-friend-modal-divider" />

        {/* Invited Friends List */}
        <div className="invite-friend-modal-friends">
          <label className="invite-friend-modal-label invite-friend-modal-label--friends">
            Invited Friends
          </label>
          <div className="invite-friend-modal-friends__list">
            {invitedFriends.length === 0 ? (
              <div className="invite-friend-modal-friends__empty">
                No friends invited yet
              </div>
            ) : (
              invitedFriends.map((friend, index) => (
                <div
                  key={index}
                  className={`invite-friend-modal-friend invite-friend-modal-friend--${friend.status}`}
                >
                  <div className="invite-friend-modal-friend__copy">
                    <div className="invite-friend-modal-friend__name">
                      {friend.username}
                    </div>
                    <div className="invite-friend-modal-friend__status">
                      {friend.status === 'joined' ? `Joined ${friend.date}` : 'Pending'}
                    </div>
                  </div>
                  {friend.status === 'joined' ? (
                    <CheckCircle2
                      className="invite-friend-modal-friend__icon invite-friend-modal-friend__icon--joined"
                      aria-hidden="true"
                    />
                  ) : (
                    <Clock3
                      className="invite-friend-modal-friend__icon invite-friend-modal-friend__icon--pending"
                      aria-hidden="true"
                    />
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      </ResponsiveModalBody>

      <ResponsiveModalFooter>
        <BeetleButton
          onClick={onClose}
          variant="secondary"
          className="invite-friend-modal-close"
        >
          Close
        </BeetleButton>
      </ResponsiveModalFooter>
    </ResponsiveModal>
  );
}
