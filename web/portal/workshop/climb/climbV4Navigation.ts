import type {ClimbStudy,ClimbViewer} from './climbModel';
// These four mappings identify the geographic destination only. Retained results
// are never transferred onto the canonical Map workshop geometry.
const canonicalIds:Record<string,string>={
 '43f15658':'43f15658-a824-438d-9925-e61c67ddabe9',
 'b51920f8':'b51920f8-4707-4984-890d-656c7078f36a',
 '4fd1981e':'4fd1981e-50a5-4abb-804a-5b7cacb7a523',
 'aec5dcc5-ea67-46ec-8b8a-4f0d77fa1862':'aec5dcc5-ea67-46ec-8b8a-4f0d77fa1862'
};
export function climbV4MapHref(study:ClimbStudy,viewer:ClimbViewer):string|null{
 if(study.id.startsWith('climb-import-'))return null;
 const id=canonicalIds[study.climbId];if(!id)return null;
 return `http://localhost:4320/?${new URLSearchParams({surface:'map',variant:'map-v2',scenario:'wises',viewer,origin:id})}`;
}
