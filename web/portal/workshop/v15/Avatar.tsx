export function Avatar({name,size=22,tone='light'}:{name:string;size?:20|22;tone?:'dark'|'light'}) {
 return <span className="v15-avatar" data-size={size} data-tone={tone} aria-hidden="true">{name.trim().split(/\s+/).slice(0,2).map(part=>Array.from(part)[0]).join('')}</span>;
}
