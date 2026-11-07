/** The current workshop destinations. Later rooms move here without changing the frame. */
export const destinations={
 feed:{surface:'feed',variant:'feed-v13',scenario:'mixed'},
 map:{surface:'map',variant:'map-v7',scenario:'wises',viewer:'rider'},
 profile:{surface:'profile',variant:'profile-v6',scenario:'rider',tab:'overview'},
 upload:{surface:'upload',variant:'upload-v1'},
 notifications:{surface:'notifications',variant:'notifications-v1'},
 settings:{surface:'settings',variant:'settings-v1'},
 climb:{surface:'climb',variant:'climb-v16'},
 ride:{surface:'ride',variant:'candidate-v14'},
} as const;
export function destinationHref(destination:keyof typeof destinations,params:Record<string,string>={}){return `/?${new URLSearchParams({...destinations[destination],...params})}`;}
export const youItems=[['overview','Profile'],['rides','Rides'],['training','Training'],['portfolio','Portfolio']].map(([id,label])=>({id,label,href:destinationHref('profile',{tab:id})}));
