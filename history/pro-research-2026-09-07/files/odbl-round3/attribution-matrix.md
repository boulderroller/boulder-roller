# Attribution and service-permission contract
Source keys resolve in sources.yaml; templates are in notice-templates.yaml. This contract is a proposed implementation, not evidence that any screen or hosted-tile use is compliant.
CARTO’s Basemap Terms dated 26 August 2026 require prominent OSM/CARTO credit, restrict server proxy/cache and alteration of service components, permit attributed illustrative/editorial/documentary static images, and address moving-vehicle displays [S4, sections 9, 13–15].
Obtain and record the entitlement for the actual CARTO endpoint, recolouring method and use while riding. An open-source style licence does not by itself authorize alteration/proxying of CARTO-hosted raster tiles. Whether a particular client display filter is a prohibited alteration requires review of the actual implementation and applicable agreement.
If these permissions remain unresolved, use an independently rendered, rights-cleared base or a profile/climb-line card without vendor tiles. Attribution cannot confer missing service rights.
AWS’s Terrain Tiles registry directs users to the upstream Terrain Tiles licence/attribution catalogue; it is not a blanket AWS licence for every input [S6–S8].
The proposed short label is Terrain: Mapzen (AWS) · Terrain sources. It is an interface label, not a mandatory AWS notice or replacement for upstream notices.
Resolve terrain source contributors for the actual region, zoom and tile-generation lineage using the upstream footprint documentation, tile metadata or source headers when available. Do not assume that raw AWS S3 responses expose the Mapzen service’s X-Imagery-Sources header. A conservative evidenced union is acceptable; unsupported guessing is not.
Keep display-terrain sources separate from canonical-profile elevation assets. The AWS tiles may include legacy EA 2015, EU-DEM, SRTM, GMTED2010 and ETOPO1 rather than the directly acquired sources in source-policy.yaml. More global contributors exist; this pack does not assert full worldwide terrain-source clearance.
## Map rooms and explorer
Visible credit: © OpenStreetMap contributors · © CARTO · Terrain: Mapzen (AWS) · Data and sources.
Link OpenStreetMap to https://www.openstreetmap.org/copyright and CARTO to https://carto.com/attributions. Data and sources opens an associated panel showing the displayed release, geographic data offer and all applicable terrain notices. Preserve any provider marks already present.
Use a legible, high-contrast map-corner credit within the safe area, not covered by controls, independent of hover/tap. A collapsible long source panel supplements rather than hides the visible OSM/CARTO attribution.
The explorer’s registration detail also links the exact canon version/geographic revision/commitment to its immutable manifest and complete data offer. Do not label the entire chain ledger ODbL.
A rendered combined map is a Produced Work from the OSM-derived geographic database. Raw queryable vector geometry or terrain arrays do not become Produced Works merely because the API calls them tiles.
## Profile graphics
Visible credit: Climb geography: © OpenStreetMap contributors. Elevation: [resolved source notice]. The associated panel identifies ODbL 1.0 and links the relevant geographic release and source licence.
A rendered canonical profile is treated as a Produced Work from the combined geographic derivative. Its downloadable sample array remains database contents. A rider-sensor-only chart is not automatically subject to these geographic credits.
Do not add CARTO or Mapzen merely because they are used elsewhere in the application; credit the inputs actually used for this graphic.
## Share-card images
A map, climb outline or canonical-profile card is treated as a Produced Work. Bake readable OSM and all actually applicable basemap/elevation credits into the image. Preserve required copyright/licence references as written URLs when they cannot be hyperlinks.
Include openstreetmap.org/copyright and a short durable public release/source-offer URL inside the image. A caption, EXIF, alt text or a QR code alone is not the implementation standard.
The complete Copernicus modified-data notice accompanies a Copernicus-derived image; its liability sentence remains in the associated distribution legal notice. A clipped or tiny footer is not accepted merely because the text is technically present.
A card containing only independent time/power observations and no geographic-derived content is not automatically a Produced Work from the geographic database.
## API JSON and downloaded data
Geographic JSON is a database extract, not automatically a Produced Work. Identify the licence scope as geographic fields, and include release/revision identity, attribution, licence URL, immutable manifest, complete source-offer URL and resolved source notices.
Preserve the matched-climbs API’s existing shape through an agreed additive metadata extension or documented Link-header/metadata-resource transition. Never replace existing result fields or apply ODbL indiscriminately to independent rider/economic fields.
Link headers use rel="license" for the licence and rel="describedby" for the associated metadata/manifest; source_offer is an explicit application metadata field. Do not claim a nonstandard relation is an Internet standard.
All downloadable geography carries its source and notice records. A server-wide all-rights-reserved response must not contradict the data licence.
## Docs
The Open data page states: Climb geography is derived from © OpenStreetMap contributors and is available under ODbL 1.0. Complete releases, schemas and source-specific notices are available here.
Technical prose is not automatically a Produced Work. Embedded maps/profile graphics follow their own surface rules; downloadable examples containing geographic records preserve source/licence metadata.
## Resolved minimum source notices
OSM credit chosen from official guidance: © OpenStreetMap contributors; online licence explanation via its copyright page, and explicit ODbL identification on data distributions [S2–S3].
CARTO credit: © CARTO, linked to its attributions page, alongside OSM. This wording implements its credit requirement but is not a permission to recolour/proxy tiles [S4].
USGS requests: Data available from U.S. Geological Survey, National Geospatial Program. Public-domain use is not conditional on that acknowledgement [S9].
EA 2022 direct DTM notice: © Environment Agency copyright and/or database right 2022. All rights reserved. Retain the OGL v3.0 link in the associated source record [S10–S11].
Legacy EA notice in the Terrain Tiles catalogue: © Environment Agency copyright and/or database right 2015. All rights reserved. Do not substitute the direct-source 2022 year [S7].
EU-DEM terrain notice: Produced using Copernicus data and information funded by the European Union - EU-DEM layers. This is not the WorldDEM-30 notice [S7].
ETOPO1 terrain credit listed upstream: Global ETOPO1 terrain data U.S. National Oceanic and Atmospheric Administration. Retain the accompanying upstream legal/warranty information in the source bundle [S7].
OS and IGN templates must be resolved from the actual asset’s supplied copyright year/source update date. An unresolved placeholder fails rendering/publication. Exact templates and Copernicus notices are in notice-templates.yaml.
Static placement here is a deliberately conservative implementation, not a claim that OSMF prohibits every alternative reasonable attribution arrangement. Additional provider terms may be stricter [S2].
