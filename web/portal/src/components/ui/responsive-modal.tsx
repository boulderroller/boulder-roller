import * as React from 'react';
import { useIsMobile } from './use-mobile';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from './dialog';
import {
  Drawer,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerDescription,
  DrawerFooter,
  DrawerClose,
} from './drawer';

interface ResponsiveModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: React.ReactNode;
  dismissible?: boolean;
}

/**
 * ResponsiveModal — Drawer on mobile (<768px), Dialog on desktop.
 *
 * Mobile: vaul Drawer from bottom, swipe-to-dismiss.
 * Desktop: centered dialog using the portal sheet surface.
 *
 * Uses compound component pattern so callers use:
 *   <ResponsiveModal>
 *     <ResponsiveModalHeader>
 *       <ResponsiveModalTitle>Title</ResponsiveModalTitle>
 *     </ResponsiveModalHeader>
 *     <ResponsiveModalBody>...content...</ResponsiveModalBody>
 *     <ResponsiveModalFooter>...actions...</ResponsiveModalFooter>
 *   </ResponsiveModal>
 */
function ResponsiveModal({ open, onOpenChange, children, dismissible = true }: ResponsiveModalProps) {
  const isMobile = useIsMobile();
  const returnFocus = React.useRef<HTMLElement | null>(null);
  React.useLayoutEffect(() => {
    if (open) returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  }, [open]);
  const restoreFocus = (event: Event) => {
    if (returnFocus.current?.isConnected) {
      event.preventDefault();
      returnFocus.current.focus();
    }
  };

  if (isMobile) {
    return (
      <Drawer open={open} onOpenChange={onOpenChange} dismissible={dismissible}>
        <DrawerContent className="portal-responsive-modal__drawer-content" onCloseAutoFocus={restoreFocus}>
          {children}
        </DrawerContent>
      </Drawer>
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="portal-responsive-modal__dialog-content"
        onInteractOutside={(event) => { if (!dismissible) event.preventDefault(); }}
        onEscapeKeyDown={(event) => { if (!dismissible) event.preventDefault(); }}
        onCloseAutoFocus={restoreFocus}
      >
        {children}
      </DialogContent>
    </Dialog>
  );
}

function ResponsiveModalHeader({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  const isMobile = useIsMobile();
  if (isMobile) {
    return <DrawerHeader className={className}>{children}</DrawerHeader>;
  }
  return <DialogHeader className={className}>{children}</DialogHeader>;
}

function ResponsiveModalTitle({ children, className = '', asChild }: { children: React.ReactNode; className?: string; asChild?: boolean }) {
  const isMobile = useIsMobile();
  if (isMobile) {
    return <DrawerTitle asChild={asChild} className={className}>{children}</DrawerTitle>;
  }
  return <DialogTitle asChild={asChild} className={className}>{children}</DialogTitle>;
}

function ResponsiveModalDescription({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  const isMobile = useIsMobile();
  if (isMobile) {
    return <DrawerDescription className={className}>{children}</DrawerDescription>;
  }
  return <DialogDescription className={className}>{children}</DialogDescription>;
}

function ResponsiveModalBody({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <div data-slot="responsive-modal-body" className={`px-4 py-2 ${className}`}>{children}</div>;
}

function ResponsiveModalFooter({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  const isMobile = useIsMobile();
  if (isMobile) {
    return <DrawerFooter className={className}>{children}</DrawerFooter>;
  }
  return <DialogFooter className={className}>{children}</DialogFooter>;
}

function ResponsiveModalClose({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  const isMobile = useIsMobile();
  if (isMobile) {
    return <DrawerClose className={className}>{children}</DrawerClose>;
  }
  return <DialogClose className={className}>{children}</DialogClose>;
}

export {
  ResponsiveModal,
  ResponsiveModalHeader,
  ResponsiveModalTitle,
  ResponsiveModalDescription,
  ResponsiveModalBody,
  ResponsiveModalFooter,
  ResponsiveModalClose,
};
