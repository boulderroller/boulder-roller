import { useMutation } from '@tanstack/react-query';
import { useState, useRef, useCallback, useEffect } from 'react';
import { api, ApiError, type RideStatus } from '../../lib/api';
import { File as FileGlyph } from 'lucide-react';
import UploadPrivacyRows from './UploadPrivacyRows';
import UploadSavedRide from './UploadSavedRide';
import { ResponsiveModal, ResponsiveModalHeader, ResponsiveModalTitle, ResponsiveModalDescription, ResponsiveModalBody } from '../ui/responsive-modal';
import '../../styles/portal-upload-sheet.css';
import { useRidePrivacy } from '../../hooks/useRidePrivacy';
import { formatFileSize } from '../../lib/formatters';
import { UPLOAD_PROCESSING_FAILURE } from './uploadCopy';

// File validation
const ALLOWED_EXTENSIONS = ['fit', 'gpx', 'tcx'];
const MAX_FILE_SIZE_MB = 50;
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;

type UploadPhase = 'idle' | 'validating' | 'uploading' | 'processing' | 'done' | 'error';

interface UploadActivitySurfaceProps {
  onClose: () => void;
  onOpenRide: (rideId: string) => void;
}

export default function UploadActivitySurface({ onClose, onOpenRide }: UploadActivitySurfaceProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const chooseFileButtonRef = useRef<HTMLButtonElement>(null);
  const uploadButtonRef = useRef<HTMLButtonElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const isMountedRef = useRef(true);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isCancelling, setIsCancelling] = useState(false);
  const uploadMutation = useMutation({ mutationFn: ({ file, options }: { file: File; options: Parameters<typeof api.uploadRide>[1] }) => api.uploadRide(file, options), retry: false });
  const [uploadProgress, setUploadProgress] = useState<UploadPhase>('idle');
  const [errorMessage, setErrorMessage] = useState('');
  const [errorDetails, setErrorDetails] = useState<string | null>(null);
  const [canRetry, setCanRetry] = useState(false);
  const [lastRideId, setLastRideId] = useState<string | null>(null);
  const [duplicateRideId, setDuplicateRideId] = useState<string | null>(null);
  const [rideStatus, setRideStatus] = useState<RideStatus | null>(null);
  const privacy = useRidePrivacy();
  const isTransferActive = uploadProgress === 'validating' || uploadProgress === 'uploading';
  const isProcessingActive = uploadProgress === 'processing';
  const isBusy = isTransferActive || isProcessingActive;

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      abortControllerRef.current?.abort();
    };
  }, []);

  // Validate file before selecting
  const validateFile = useCallback((file: File): { valid: boolean; error?: string } => {
    // Check extension
    const ext = file.name.split('.').pop()?.toLowerCase();
    if (!ext || !ALLOWED_EXTENSIONS.includes(ext)) {
      return { valid: false, error: 'Choose a FIT, GPX, or TCX file.' };
    }

    // Check file size
    if (file.size > MAX_FILE_SIZE_BYTES) {
      return { valid: false, error: `Choose a file smaller than ${formatFileSize(MAX_FILE_SIZE_BYTES)}.` };
    }

    // Check file is not empty
    if (file.size === 0) {
      return { valid: false, error: 'This file is empty. Choose another ride file.' };
    }

    return { valid: true };
  }, []);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (isBusy) return;
    const file = e.target.files?.[0];
    if (file) {
      const validation = validateFile(file);
      if (!validation.valid) {
        setSelectedFile(null);
        setErrorMessage(validation.error || 'Invalid file');
        setErrorDetails(null);
        setCanRetry(false);
        return;
      }
      setSelectedFile(file);
      setUploadProgress('idle');
      setDuplicateRideId(null);
      setLastRideId(null);
      setRideStatus(null);
      setErrorMessage('');
      setErrorDetails(null);
      setCanRetry(false);
    }
  };

  const handleCancel = useCallback(() => {
    if (!isTransferActive || isCancelling) return;
    setIsCancelling(true);
    setErrorDetails(null);
    setErrorMessage('Cancelling');
    abortControllerRef.current?.abort();
  }, [isCancelling, isTransferActive]);

  const handleUpload = async () => {
    if (!selectedFile || !privacy.choice || isBusy || abortControllerRef.current) return;

    // Create abort controller for cancellation
    const uploadController = new AbortController();
    abortControllerRef.current = uploadController;

    setUploadProgress('validating');
    setErrorMessage('');
    setErrorDetails(null);
    setCanRetry(false);
    setIsCancelling(false);
    setRideStatus(null);
    setDuplicateRideId(null);
    setLastRideId(null);

    try {
      // Validate file one more time
      const validation = validateFile(selectedFile);
      if (!validation.valid) {
        throw new Error(validation.error || 'Invalid file');
      }

      // Upload to backend
      setUploadProgress('uploading');
      const result = await uploadMutation.mutateAsync({ file: selectedFile, options: {
        signal: uploadController.signal,
        privacy: privacy.choice,
      } });
      if (!isMountedRef.current) return;
      setLastRideId(result.rideId);

      // Poll for processing status
      setUploadProgress('processing');
      let status = result.status;
      let attempts = 0;
      const maxAttempts = 60; // 60 seconds max polling

      while ((status === 'processing' || status === 'pending') && attempts < maxAttempts) {
        // Check if cancelled
        if (abortControllerRef.current?.signal.aborted) {
          throw new Error('Upload cancelled');
        }

        await new Promise(r => setTimeout(r, 1000));
        if (!isMountedRef.current) return;

        try {
          const statusResult = await api.getRideStatus(result.rideId, { signal: uploadController.signal });
          if (!isMountedRef.current) return;
          status = statusResult.status;
          setRideStatus(statusResult);
          if (status === 'metrics_ready' || status === 'enriched') {
            setUploadProgress('done');
            return;
          }
        } catch (err) {
          // Status check failed - show message but continue polling
          if (err instanceof ApiError && err.type === 'network_error') {
            setErrorDetails('Connection dipped. Still checking.');
          }
        }
        attempts++;
      }

      if (status === 'completed' || status === 'patterns_detected') {
        setUploadProgress('done');
      } else if (status === 'failed') {
        // Check if ride was actually created (processing may have failed but data is there)
        try {
          const ride = await api.getRide(result.rideId);
          if (ride && ride.distanceM && ride.durationS) {
            // Ride has core data - processing partially succeeded
            setUploadProgress('done');
            return;
          }
        } catch {
          // Ride doesn't exist
        }
        setCanRetry(true);
        throw new Error(UPLOAD_PROCESSING_FAILURE);
      } else if (attempts >= maxAttempts) {
        // Timeout - processing is taking too long
        setCanRetry(true);
        setLastRideId(result.rideId);
        throw new Error('This ride is still processing. Check again shortly.');
      } else {
        // Still processing - let user continue anyway
        setUploadProgress('done');
      }
    } catch (err) {
      if (!isMountedRef.current) return;
      setUploadProgress('error');

      if (
        (err instanceof Error && (err.message === 'Upload cancelled' || err.message === 'Request cancelled'))
        || (err instanceof ApiError && err.statusCode === 499)
      ) {
        setErrorMessage('Upload cancelled');
        setCanRetry(true);
        return;
      }

      if (err instanceof ApiError) {
        if (err.type === 'network_error') {
          setErrorMessage('No connection. Try again.');
          setCanRetry(true);
        } else if (err.statusCode === 409 || err.message.includes('duplicate') || err.detail?.error === 'duplicate_file') {
          // Duplicate file detected
          setErrorMessage('This ride is already in your log.');
          const existingId = (err.detail?.existing_ride_id ?? err.detail?.existingRideId) as string | undefined;
          if (existingId) {
            setDuplicateRideId(existingId);
            setErrorDetails('Open the ride already in your log.');
          } else {
            setErrorDetails('It is already in your activity log.');
          }
          setCanRetry(false);
        } else if (err.message.includes('parse') || err.message.includes('invalid') || err.message.includes('decode')) {
          setErrorMessage('Could not read this file.');
          setErrorDetails('Try exporting the original file again.');
          setCanRetry(false);
        } else if (err.message.includes('base64')) {
          setErrorMessage('Could not read this file.');
          setErrorDetails('Try exporting the original file again.');
          setCanRetry(false);
        } else {
          setErrorMessage('Could not save ride. Try again.');
          setCanRetry(true);
        }
      } else {
        setErrorMessage(err instanceof Error ? err.message : 'Could not save ride. Try again.');
        setCanRetry(true);
      }
    } finally {
      if (isMountedRef.current) {
        setIsCancelling(false);
      }
      abortControllerRef.current = null;
    }
  };

  const handleRetry = () => {
    setUploadProgress('idle');
    setErrorMessage('');
    setErrorDetails(null);
    setDuplicateRideId(null);
    setIsCancelling(false);
    handleUpload();
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    if (isBusy) return;
    const file = e.dataTransfer.files?.[0];
    if (file) {
      const validation = validateFile(file);
      if (!validation.valid) {
        setSelectedFile(null);
        setErrorMessage(validation.error || 'Invalid file');
        setErrorDetails(null);
        setCanRetry(false);
        return;
      }
      setSelectedFile(file);
      setUploadProgress('idle');
      setDuplicateRideId(null);
      setLastRideId(null);
      setRideStatus(null);
      setErrorMessage('');
      setErrorDetails(null);
      setCanRetry(false);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const chooseFile = () => {
    if (isBusy || !fileInputRef.current) return;
    fileInputRef.current.value = '';
    fileInputRef.current.click();
  };

  const selectedFileSize = selectedFile ? formatFileSize(selectedFile.size) : null;
  const isInitialChoice = uploadProgress === 'idle' && !selectedFile;
  const isSaved = uploadProgress === 'done';
  const isDuplicate = errorMessage === 'This ride is already in your log.';
  const closeWord = isSaved || isDuplicate || uploadProgress === 'error' ? 'Close' : 'Cancel';
  const activeRung = isTransferActive ? 0 : rideStatus?.phase1CompletedAt ? 2 : 1;

  // The board admits only these sentences. Keep today's error/retry decisions,
  // and leave unavailable detail/progress slots empty instead of inventing copy.
  const admittedErrors = [
    'Choose a FIT, GPX, or TCX file.',
    'This ride is already in your log.',
    'Could not read this file.',
    'Could not save ride. Try again.',
    'No connection. Try again.',
  ];
  const visibleError = !errorMessage || isCancelling || errorMessage === 'Upload cancelled'
    ? ''
    : admittedErrors.includes(errorMessage)
      ? errorMessage
      : !selectedFile ? 'Could not read this file.' : 'Could not save ride. Try again.';
  const visibleDetail = errorDetails === 'Open the ride already in your log.'
    || errorDetails === 'Try exporting the original file again.' ? errorDetails : '';

  const dismiss = () => {
    // Dismissal retains the existing abort-on-unmount contract during both
    // transfer and status polling; it never cancels a saved ride on the server.
    abortControllerRef.current?.abort();
    onClose();
  };
  const chooseAnotherFile = () => {
    setUploadProgress('idle');
    setSelectedFile(null);
    setErrorMessage('');
    setErrorDetails(null);
    setDuplicateRideId(null);
    setLastRideId(null);
    setRideStatus(null);
    setCanRetry(false);
    chooseFile();
  };

  useEffect(() => {
    if (selectedFile && uploadProgress === 'idle') {
      uploadButtonRef.current?.focus();
    } else if (!selectedFile && uploadProgress === 'idle' && errorMessage) {
      chooseFileButtonRef.current?.focus();
    }
  }, [errorMessage, selectedFile, uploadProgress]);

  return (
    <ResponsiveModal open={true} dismissible={!isBusy} onOpenChange={(open) => { if (!open) dismiss(); }}>
      <ResponsiveModalHeader className="portal-sheet__bar upload-sheet__bar">
        <ResponsiveModalTitle asChild><h1 className="portal-sheet__bar-title">Upload ride</h1></ResponsiveModalTitle>
        <ResponsiveModalDescription className="sr-only">Choose a FIT, GPX, or TCX file.</ResponsiveModalDescription>
        <button type="button" className="portal-sheet__done" onClick={isTransferActive ? handleCancel : dismiss} disabled={isCancelling}>{closeWord}</button>
      </ResponsiveModalHeader>
      <ResponsiveModalBody className="portal-sheet upload-sheet">
        <input ref={fileInputRef} type="file" accept=".fit,.gpx,.tcx" onChange={handleFileSelect} disabled={isBusy} className="hidden" />
        <div className="upload-sheet__body">
          {isInitialChoice ? <>
            <div className="upload-sheet__field" onDrop={handleDrop} onDragOver={handleDragOver}>
              <strong>Choose a FIT, GPX, or TCX file.</strong>
              <small>Upload a ride to see its climbs, times, and leaderboard positions.</small>
            </div>
            <div className="upload-sheet__group">
              <button ref={chooseFileButtonRef} type="button" className="upload-sheet__row" onClick={chooseFile}>
                <span className="upload-sheet__mark"><FileGlyph size={18} aria-hidden="true" /></span>
                <span className="upload-sheet__identity"><strong>Choose file</strong></span>
                <span className="upload-sheet__chevron" aria-hidden="true">›</span>
              </button>
            </div>
          </> : selectedFile && !isSaved ? (
            <div className="upload-sheet__group" onDrop={handleDrop} onDragOver={handleDragOver}>
              <div className="upload-sheet__row upload-sheet__file" data-file-state={uploadProgress}>
                <span className="upload-sheet__mark"><FileGlyph size={18} aria-hidden="true" /></span>
                <span className="upload-sheet__identity"><strong>{selectedFile.name}</strong><small>{selectedFileSize}</small></span>
                {isBusy ? (
                  <span className="upload-sheet__value" data-upload-bytes>
                    {isProcessingActive ? `${selectedFileSize} / ${selectedFileSize}` : null}
                  </span>
                ) : (
                  <button type="button" className="upload-sheet__word" onClick={chooseAnotherFile}>
                    Choose another file<span className="upload-sheet__chevron" aria-hidden="true">›</span>
                  </button>
                )}
              </div>
            </div>
          ) : null}

          {isBusy && (
            <ol className="upload-sheet__group upload-sheet__ladder" aria-label="Status" aria-live="polite">
              {['Saving file', 'Reading ride file', 'Matching climbs'].map((label, index) => (
                <li className="upload-sheet__row" key={label} data-state={index === activeRung ? 'live' : index < activeRung ? 'done' : 'waiting'} aria-current={index === activeRung ? 'step' : undefined}>
                  <span className="upload-sheet__mark"><span className="upload-sheet__dot" aria-hidden="true" /></span>
                  <span className="upload-sheet__identity"><strong>{label}</strong></span>
                  <span className="upload-sheet__word" data-upload-percent />
                </li>
              ))}
            </ol>
          )}

          {visibleError && <div className="upload-sheet__error">
            <p className="upload-activity-modal-error-message" role="alert">{visibleError}</p>
            {visibleDetail && <p className="upload-activity-modal-error-detail">{visibleDetail}</p>}
          </div>}

          {isSaved && lastRideId ? (
            <UploadSavedRide rideId={lastRideId} status={rideStatus} onOpenRide={onOpenRide} />
          ) : isDuplicate ? (
            duplicateRideId && <UploadSavedRide rideId={duplicateRideId} duplicate onOpenRide={onOpenRide} />
          ) : (
            <UploadPrivacyRows privacy={privacy} frozen={uploadProgress !== 'idle'} />
          )}
        </div>
        <footer className={`upload-sheet__footer${isBusy ? ' upload-sheet__footer--busy' : ''}`}>
          {isSaved && lastRideId ? <>
            <button type="button" className="upload-sheet__action upload-sheet__action--commit" onClick={() => onOpenRide(lastRideId)}>Open ride</button>
            <button type="button" className="upload-sheet__action upload-sheet__action--quiet" onClick={dismiss}>Close</button>
          </> : isDuplicate ? <>
            {duplicateRideId && <button type="button" className="upload-sheet__action" onClick={() => onOpenRide(duplicateRideId)}>Open saved ride</button>}
            <button type="button" className="upload-sheet__action upload-sheet__action--quiet" onClick={dismiss}>Close</button>
          </> : uploadProgress === 'error' ? <>
            {canRetry && <button type="button" className="upload-sheet__action" onClick={handleRetry}>Try again</button>}
            <button type="button" className={`upload-sheet__action${canRetry ? ' upload-sheet__action--quiet' : ''}`} onClick={chooseAnotherFile}>Choose another file</button>
            {!canRetry && <button type="button" className="upload-sheet__action upload-sheet__action--quiet" onClick={dismiss}>Close</button>}
          </> : isBusy ? (
            <button type="button" className="upload-sheet__action upload-sheet__action--quiet" onClick={isTransferActive ? handleCancel : dismiss} disabled={isCancelling}>Cancel</button>
          ) : <>
            <button ref={uploadButtonRef} type="button" className="upload-sheet__action upload-sheet__action--commit" onClick={handleUpload} disabled={!selectedFile || !privacy.choice || privacy.isLoading || Boolean(privacy.error) || isBusy}>Upload ride</button>
            {!isInitialChoice && <button type="button" className="upload-sheet__action upload-sheet__action--quiet" onClick={dismiss}>Cancel</button>}
          </>}
        </footer>
      </ResponsiveModalBody>
    </ResponsiveModal>
  );
}
