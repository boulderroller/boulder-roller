import { useCallback, useRef, useState } from 'react';

type CopyButtonProps = {
  text: string;
};

export default function CopyButton({ text }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  const handleClick = useCallback(() => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setCopied(false), 1500);
    }).catch(() => {});
  }, [text]);

  return (
    <button
      type="button"
      className="copy-button"
      onClick={handleClick}
      aria-label={copied ? 'Copied' : 'Copy to clipboard'}
    >
      {copied ? (
        <span className="copy-button__label">Copied!</span>
      ) : (
        <svg
          width="14"
          height="14"
          viewBox="0 0 14 14"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          aria-hidden="true"
        >
          <rect x="4.5" y="4.5" width="8" height="8" rx="1.5" stroke="currentColor" strokeWidth="1.2" />
          <path d="M9.5 4.5V2.5a1.5 1.5 0 0 0-1.5-1.5H2.5A1.5 1.5 0 0 0 1 2.5V8a1.5 1.5 0 0 0 1.5 1.5h2" stroke="currentColor" strokeWidth="1.2" />
        </svg>
      )}
    </button>
  );
}
