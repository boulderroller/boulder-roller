import type {SymbolLayerSpecification} from 'maplibre-gl';

/** Symbols describe only the existing tile feature classification. No new geography. */
export function landmarkLayers():SymbolLayerSpecification[]{
 const layout:SymbolLayerSpecification['layout']={
  'text-field':['get','name'],'text-font':['Montserrat Medium','Open Sans Bold'],
  'text-size':10.5,'text-anchor':'top','text-offset':[0,1.05],'text-max-width':12,
  'icon-size':.9,'icon-padding':6,'text-padding':4,
  'icon-allow-overlap':false,'text-allow-overlap':false,
  'symbol-sort-key':['coalesce',['get','rank'],100],
 };
 const paint:SymbolLayerSpecification['paint']={'text-color':'#64715d','text-halo-color':'#f0f1eb','text-halo-width':1.5,'icon-opacity':.85};
 return [
  {id:'m5-landmarks',type:'symbol',source:'carto','source-layer':'poi',minzoom:14,filter:['all',['has','name'],['!=',['get','name'],''],['any',['==',['get','class'],'museum'],['==',['get','class'],'castle'],['all',['==',['get','class'],'attraction'],['==',['get','subclass'],'viewpoint']]]],layout:{...layout,'icon-image':['match',['get','class'],'museum','m5-museum','castle','m5-historic','m5-viewpoint']},paint},
  {id:'m5-shelters',type:'symbol',source:'carto','source-layer':'poi',minzoom:15,filter:['all',['has','name'],['!=',['get','name'],''],['==',['get','class'],'shelter']],layout:{...layout,'icon-image':'m5-shelter'},paint},
 ];
}
