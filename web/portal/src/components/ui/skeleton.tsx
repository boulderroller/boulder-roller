import { Slot } from '../loading/Slot';
/** Compatibility export; all pending values use the same primitive. */
export function Skeleton(props: React.ComponentProps<typeof Slot>) { return <Slot {...props} />; }
