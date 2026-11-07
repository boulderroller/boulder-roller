import { useState } from 'react';
import { BeetleButton } from '../ui/beetle-button';
import { BeetleInput } from '../ui/beetle-input';
import {
  ResponsiveModal,
  ResponsiveModalHeader,
  ResponsiveModalTitle,
  ResponsiveModalDescription,
  ResponsiveModalBody,
  ResponsiveModalFooter,
} from '../ui/responsive-modal';
import { useFormatters } from '../../hooks/useFormatters';

interface Activity {
  id: string;
  title: string;
  description: string;
  distance: number;
  duration: string;
  date: string;
  visibility: 'public' | 'followers' | 'private';
  commentsEnabled: boolean;
  hideFromLeaderboards: boolean;
}

interface EditActivityModalProps {
  activity: Activity;
  onClose: () => void;
  onSave: (updatedActivity: Activity) => void;
}

export default function EditActivityModal({ activity, onClose, onSave }: EditActivityModalProps) {
  const { distance: formatDistance } = useFormatters();
  const [title, setTitle] = useState(activity.title);
  const [description, setDescription] = useState(activity.description);
  const [visibility, setVisibility] = useState(activity.visibility);
  const [commentsEnabled, setCommentsEnabled] = useState(activity.commentsEnabled);
  const [hideFromLeaderboards, setHideFromLeaderboards] = useState(activity.hideFromLeaderboards);

  const handleSave = () => {
    onSave({
      ...activity,
      title,
      description,
      visibility,
      commentsEnabled,
      hideFromLeaderboards,
    });
  };

  return (
    <ResponsiveModal open={true} onOpenChange={(open) => { if (!open) onClose(); }}>
      <ResponsiveModalHeader>
        <ResponsiveModalTitle className="edit-activity-modal-title">
          ✏️ Edit Activity
        </ResponsiveModalTitle>
        <ResponsiveModalDescription className="sr-only">
          Update ride details, visibility, comments, and leaderboard settings.
        </ResponsiveModalDescription>
      </ResponsiveModalHeader>

      <ResponsiveModalBody className="edit-activity-modal-body">
        <div className="edit-activity-modal-summary">
          <div className="edit-activity-modal-summary__list">
            <div className="edit-activity-modal-summary__item">
              <div className="edit-activity-modal-label">
                Distance
              </div>
              <div className="edit-activity-modal-summary__value">
                {formatDistance(activity.distance * 1000)}
              </div>
            </div>
            <div className="edit-activity-modal-summary__item">
              <div className="edit-activity-modal-label">
                Duration
              </div>
              <div className="edit-activity-modal-summary__value">
                {activity.duration}
              </div>
            </div>
            <div className="edit-activity-modal-summary__item">
              <div className="edit-activity-modal-label">
                Date
              </div>
              <div className="edit-activity-modal-summary__value edit-activity-modal-summary__value--date">
                {activity.date}
              </div>
            </div>
          </div>
        </div>

        <div className="edit-activity-modal-field">
          <label className="edit-activity-modal-label">
            Title
          </label>
          <BeetleInput
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Activity title"
          />
        </div>

        <div className="edit-activity-modal-field edit-activity-modal-field--description">
          <label className="edit-activity-modal-label" htmlFor="edit-activity-description">
            Notes
          </label>
          <textarea
            id="edit-activity-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Add ride notes..."
            rows={3}
            className="edit-activity-modal-textarea"
          />
        </div>

        <div className="edit-activity-modal-settings">
          <div className="edit-activity-modal-label edit-activity-modal-label--settings">
            Sharing
          </div>

          <div className="edit-activity-modal-option-list edit-activity-modal-option-list--visibility">
            <label className="edit-activity-modal-option">
              <input
                type="radio"
                name="visibility"
                checked={visibility === 'public'}
                onChange={() => setVisibility('public')}
                className="edit-activity-modal-option__control"
              />
              <div className="edit-activity-modal-option__label">
                Public
              </div>
            </label>

            <label className="edit-activity-modal-option">
              <input
                type="radio"
                name="visibility"
                checked={visibility === 'followers'}
                onChange={() => setVisibility('followers')}
                className="edit-activity-modal-option__control"
              />
              <div className="edit-activity-modal-option__label">
                Followers
              </div>
            </label>

            <label className="edit-activity-modal-option">
              <input
                type="radio"
                name="visibility"
                checked={visibility === 'private'}
                onChange={() => setVisibility('private')}
                className="edit-activity-modal-option__control"
              />
              <div className="edit-activity-modal-option__label">
                Private
              </div>
            </label>
          </div>

          <div className="edit-activity-modal-option-list">
            <label className="edit-activity-modal-option">
              <input
                type="checkbox"
                checked={commentsEnabled}
                onChange={(e) => setCommentsEnabled(e.target.checked)}
                className="edit-activity-modal-option__control"
              />
              <div className="edit-activity-modal-option__label">
                Enable notes
              </div>
            </label>

            <label className="edit-activity-modal-option">
              <input
                type="checkbox"
                checked={hideFromLeaderboards}
                onChange={(e) => setHideFromLeaderboards(e.target.checked)}
                className="edit-activity-modal-option__control"
              />
              <div className="edit-activity-modal-option__label">
                Keep off leaderboards
              </div>
            </label>
          </div>
        </div>
      </ResponsiveModalBody>

      <ResponsiveModalFooter className="edit-activity-modal-footer">
        <BeetleButton
          variant="secondary"
          onClick={onClose}
          className="edit-activity-modal-action"
        >
          Cancel
        </BeetleButton>
        <BeetleButton
          onClick={handleSave}
          className="edit-activity-modal-action"
        >
          Save Changes
        </BeetleButton>
      </ResponsiveModalFooter>
    </ResponsiveModal>
  );
}
