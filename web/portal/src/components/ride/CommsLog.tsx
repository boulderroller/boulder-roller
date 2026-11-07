import { memo, useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { api, Comment } from '../../lib/api';
import { getPublicRiderDisplayName, getPublicRiderPath } from '../../lib/riderIdentity';
import { formatDateTime } from '../../lib/formatters';
import { toast } from 'sonner';
import { Check, Edit3, Flag, Send, Trash2, X } from 'lucide-react';

interface CommsLogProps {
  rideId: string;
  ledger?: boolean;
  canComment?: boolean;
  onChange?: () => void;
}

const CommsLog = memo(({ rideId, ledger = false, canComment = true, onChange }: CommsLogProps) => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [comments, setComments] = useState<Comment[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [newMessage, setNewMessage] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [editingCommentId, setEditingCommentId] = useState<string | null>(null);
  const [editingContent, setEditingContent] = useState('');
  const [isUpdating, setIsUpdating] = useState(false);
  const [deletingCommentId, setDeletingCommentId] = useState<string | null>(null);
  const [reportingCommentId, setReportingCommentId] = useState<string | null>(null);

  const fetchComments = useCallback(async () => {
    try {
      setIsLoading(true);
      setLoadError(null);
      const response = await api.getRideComments(rideId);
      setComments(response.comments || []);
    } catch {
      setComments([]);
      setLoadError('Comments could not load.');
    } finally {
      setIsLoading(false);
    }
  }, [rideId]);

  useEffect(() => {
    void fetchComments();
  }, [fetchComments]);

  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newMessage.trim() || isSubmitting) return;

    try {
      setIsSubmitting(true);
      const comment = await api.addRideComment(rideId, newMessage.trim());
      setComments(prev => [...prev, comment]);
      setNewMessage('');
      onChange?.();
      toast.success('Comment posted');
    } catch {
      toast.error('Could not post comment');
    } finally {
      setIsSubmitting(false);
    }
  }, [rideId, newMessage, isSubmitting, onChange]);

  const startEdit = useCallback((comment: Comment) => {
    setEditingCommentId(comment.id);
    setEditingContent(comment.content);
  }, []);

  const cancelEdit = useCallback(() => {
    setEditingCommentId(null);
    setEditingContent('');
  }, []);

  const handleUpdateComment = useCallback(async (commentId: string) => {
    const content = editingContent.trim();
    if (!content || isUpdating) return;

    try {
      setIsUpdating(true);
      const updated = await api.updateRideComment(rideId, commentId, content);
      setComments(prev => prev.map(comment => comment.id === commentId ? updated : comment));
      cancelEdit();
      toast.success('Comment updated');
    } catch {
      toast.error('Could not update comment');
    } finally {
      setIsUpdating(false);
    }
  }, [rideId, editingContent, isUpdating, cancelEdit]);

  const handleDeleteComment = useCallback(async (commentId: string) => {
    if (deletingCommentId) return;

    try {
      setDeletingCommentId(commentId);
      await api.deleteRideComment(rideId, commentId);
      setComments(prev => prev.filter(comment => comment.id !== commentId));
      onChange?.();
      toast.success('Comment deleted');
    } catch {
      toast.error('Could not delete comment');
    } finally {
      setDeletingCommentId(null);
    }
  }, [rideId, deletingCommentId, onChange]);

  const handleReportComment = useCallback(async (commentId: string) => {
    if (reportingCommentId) return;

    try {
      setReportingCommentId(commentId);
      const report = await api.reportSocialContent(
        'comment',
        commentId,
        'other',
        'Reported from ride comments',
      );
      setComments(prev => prev.map(comment => (
        comment.id === commentId
          ? { ...comment, viewerReported: true, reportStatus: report.status }
          : comment
      )));
      toast.success('Report sent');
    } catch {
      toast.error('Could not report comment');
    } finally {
      setReportingCommentId(null);
    }
  }, [reportingCommentId]);

  const openCommentAuthor = useCallback((comment: Comment) => {
    navigate(getPublicRiderPath({
      id: comment.userId,
      userId: comment.userId,
      username: comment.username,
      displayName: comment.displayName,
    }));
  }, [navigate]);

  return (
    <div className="ride-comments">
        <div className="ride-comments__body">
            {ledger && (isLoading || loadError || !comments.length) ? null : isLoading ? (
              <div className="ride-comments__state">
                Loading comments
              </div>
            ) : loadError ? (
              <div className="ride-comments__state ride-comments__state--error">
                <span>{loadError}</span>
                <button type="button" onClick={() => void fetchComments()}>
                  Try again
                </button>
              </div>
            ) : comments.length === 0 ? (
              <div className="ride-comments__state">
                No comments yet
              </div>
            ) : (
              comments.map((comment) => {
                const isOwnComment = comment.userId === user?.id;
                const isEditing = editingCommentId === comment.id;
                const authorName = getPublicRiderDisplayName({
                  id: comment.userId,
                  userId: comment.userId,
                  username: comment.username,
                  displayName: comment.displayName,
                });
                return (
                <div
                    key={comment.id}
                    className="ride-comments__entry"
                >
                    <div className="ride-comments__avatar" aria-hidden="true">
                      {authorName.slice(0, 1).toUpperCase()}
                    </div>
                    <div className="ride-comments__entry-content">
                      <div className="ride-comments__entry-meta">
                        <button
                          type="button"
                          className="ride-comments__entry-author"
                          onClick={() => openCommentAuthor(comment)}
                        >
                          {isOwnComment ? 'You' : authorName}
                        </button>
                        <span className="ride-comments__entry-time">{formatDateTime(comment.createdAt)}</span>
                      </div>
                      <div className="ride-comments__entry-body">
                        {isEditing ? (
                          <input
                            value={editingContent}
                            onChange={(event) => setEditingContent(event.target.value)}
                            className="ride-comments__edit-input"
                            autoFocus
                          />
                        ) : (
                          <div className="ride-comments__message">
                              {comment.content}
                              {comment.viewerReported && (
                                <span className="ride-comments__reported-badge">
                                  {comment.reportStatus || 'reported'}
                                </span>
                              )}
                          </div>
                        )}
                        {(isOwnComment || user) && (
                          <div className="ride-comments__actions">
                            {isOwnComment && isEditing ? (
                              <>
                                <button
                                  type="button"
                                  className="ride-comments__icon-button"
                                  disabled={isUpdating || !editingContent.trim()}
                                  onClick={() => handleUpdateComment(comment.id)}
                                  aria-label="Save comment"
                                >
                                  <Check size={12} />
                                </button>
                                <button type="button" className="ride-comments__icon-button" onClick={cancelEdit} aria-label="Cancel edit">
                                  <X size={12} />
                                </button>
                              </>
                            ) : isOwnComment ? (
                              <>
                                <button type="button" className="ride-comments__icon-button" onClick={() => startEdit(comment)} aria-label="Edit comment">
                                  <Edit3 size={12} />
                                </button>
                                <button
                                  type="button"
                                  className="ride-comments__icon-button"
                                  disabled={deletingCommentId === comment.id}
                                  onClick={() => handleDeleteComment(comment.id)}
                                  aria-label="Delete comment"
                                >
                                  <Trash2 size={12} />
                                </button>
                              </>
                            ) : (
                              <button
                                type="button"
                                className="ride-comments__icon-button"
                                disabled={comment.viewerReported || reportingCommentId === comment.id}
                                onClick={() => handleReportComment(comment.id)}
                                aria-label="Report comment"
                                title={comment.viewerReported ? 'Already reported' : 'Report comment'}
                              >
                                <Flag size={12} />
                              </button>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                </div>
              );
            })
            )}
        </div>
        {canComment && <form onSubmit={handleSubmit} className="ride-comments__form">
            <input
                type="text"
                placeholder="Add a comment..."
                value={newMessage}
                onChange={(e) => setNewMessage(e.target.value)}
                disabled={isSubmitting}
                className="ride-comments__input"
            />
            <button
              type="submit"
              className="ride-comments__submit"
              disabled={!newMessage.trim() || isSubmitting}
              aria-label="Post comment"
            >
              <Send size={14} />
            </button>
        </form>}
    </div>
  );
});

CommsLog.displayName = 'CommsLog';

export default CommsLog;
