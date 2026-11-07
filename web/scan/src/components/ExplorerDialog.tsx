import { forwardRef, type DialogHTMLAttributes } from "react";
/** The Search sheet is the shared modal ledger surface. */
const ExplorerDialog = forwardRef<
  HTMLDialogElement,
  DialogHTMLAttributes<HTMLDialogElement>
>(function ExplorerDialog({ className = "", ...props }, ref) {
  return (
    <dialog
      ref={ref}
      className={`observatory-search-sheet ${className}`}
      {...props}
    />
  );
});
export default ExplorerDialog;
