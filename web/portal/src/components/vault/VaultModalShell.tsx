import type { CSSProperties, HTMLAttributes, ReactNode } from 'react';

interface VaultModalBackdropProps {
  onClick?: () => void;
  textured?: boolean;
  zIndexClassName?: string;
}

export function VaultModalBackdrop({
  onClick,
  textured = false,
  zIndexClassName = 'vault-modal-backdrop--layer-backdrop',
}: VaultModalBackdropProps) {
  return (
    <div
      className={[
        'vault-modal-backdrop',
        textured ? 'vault-modal-backdrop--textured' : '',
        zIndexClassName,
      ].filter(Boolean).join(' ')}
      onClick={onClick}
    />
  );
}

interface VaultModalFrameProps {
  children: ReactNode;
  maxWidth?: number | string;
  zIndexClassName?: string;
}

export function VaultModalFrame({
  children,
  maxWidth = 440,
  zIndexClassName = 'vault-modal-frame--layer-frame',
}: VaultModalFrameProps) {
  const resolvedMaxWidth = typeof maxWidth === 'number' ? `${maxWidth}px` : maxWidth;
  const frameStyle = {
    '--vault-modal-frame-max-width': resolvedMaxWidth,
  } as CSSProperties;

  return (
    <div
      className={['vault-modal-frame', zIndexClassName].filter(Boolean).join(' ')}
      style={frameStyle}
    >
      {children}
    </div>
  );
}

export function VaultModalPanel({
  children,
  className = '',
  style,
  ...rest
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={['vault-modal-panel', className].filter(Boolean).join(' ')}
      style={style}
      {...rest}
    >
      {children}
    </div>
  );
}
