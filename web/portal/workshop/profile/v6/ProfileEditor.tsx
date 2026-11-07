import {useEffect,useRef,useState} from 'react';
import {rideImage} from './RideEntry';
import {type Person} from './profileV6Model';

export function ProfileEditor({person,onSave}:{person:Person;onSave:(person:Person)=>void}){
 const [draft,setDraft]=useState(person),[error,setError]=useState(''),[pending,setPending]=useState({cover:false,portrait:false}),requests=useRef({cover:0,portrait:0});
 useEffect(()=>()=>{requests.current.cover++;requests.current.portrait++;},[]);
 const loadPhoto=async(file:File|undefined,field:'cover'|'portrait')=>{
  if(!file)return;
  const request=++requests.current[field];setPending(p=>({...p,[field]:false}));
  if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>2*1024*1024){setError('Choose a PNG, JPEG or WebP photograph under 2 MB.');return;}
  setPending(p=>({...p,[field]:true}));setError('');
  try{
   const src=await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result));reader.onerror=()=>reject(Error());reader.readAsDataURL(file);});
   await new Promise<void>((resolve,reject)=>{const img=new Image();img.onload=()=>resolve();img.onerror=()=>reject(Error());img.src=src;});
   if(requests.current[field]===request){setDraft(p=>({...p,[field]:src}));setError('');}
  }catch{if(requests.current[field]===request)setError('This photograph could not be opened.');}finally{if(requests.current[field]===request)setPending(p=>({...p,[field]:false}));}
 };
 return <form className="p6-profile-editor" onSubmit={e=>{e.preventDefault();if(pending.cover||pending.portrait)return;if(!draft.name.trim()){setError('Enter a name.');return;}try{onSave({...draft,name:draft.name.trim(),location:draft.location.trim(),bio:draft.bio.trim()});}catch(e){setError(e instanceof Error?e.message:'The profile could not be saved.');}}}>
  <div className="p6-photo-choices">{(['cover','portrait'] as const).map(field=><div key={field}><span>{field==='cover'?'Banner':'Profile photo'}</span><div className={`p6-image-choice ${field}`}>{draft[field]?<img src={rideImage(draft[field]!)} alt={field==='cover'?'Current banner':'Current profile photograph'}/>:<span>No photograph</span>}</div><label className="p6-photo-upload">{pending[field]?'Opening photo…':'Choose photo'}<input aria-label={field==='cover'?'Choose banner photograph':'Choose profile photograph'} type="file" accept="image/png,image/jpeg,image/webp" onChange={e=>{void loadPhoto(e.target.files?.[0],field);e.target.value='';}}/></label>{draft[field]&&<button className="p6-remove-photo" type="button" aria-label={field==='cover'?'Remove banner photograph':'Remove profile photograph'} onClick={()=>{requests.current[field]++;setPending(p=>({...p,[field]:false}));setDraft(p=>({...p,[field]:null}));}}>Remove</button>}</div>)}</div>
  <label>Name<input name="name" required maxLength={120} value={draft.name} onChange={e=>setDraft(p=>({...p,name:e.target.value}))}/></label>
  <label>Location<input name="location" maxLength={200} value={draft.location} onChange={e=>setDraft(p=>({...p,location:e.target.value}))}/></label>
  <label>Bio<textarea name="bio" maxLength={2000} value={draft.bio} onChange={e=>setDraft(p=>({...p,bio:e.target.value}))}/></label>
  {error&&<p role="alert" className="p6-edit-error">{error}</p>}
  <button type="submit" disabled={pending.cover||pending.portrait}>Save profile</button>
 </form>;
}
