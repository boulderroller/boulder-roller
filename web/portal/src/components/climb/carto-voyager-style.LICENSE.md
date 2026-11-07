# carto-voyager-style.json

CARTO's Voyager GL style, served with the portal and BoulderScan as the base of the
map ground. The two copies (web/portal/src/components/climb and
web/scan/src/components/ground) stay byte-identical; tests in both apps check it.

- Source: https://github.com/CartoDB/basemap-styles/blob/6f8f9332bac3cbd15b132359494afdb1a04d48e7/mapboxgl/voyager.json
- Changes: the `carto` source reads our own OpenMapTiles-schema PMTiles, and `glyphs`
  and `sprite` read our own builds, all under https://api.boulderroller.xyz/basemap/
  (tools/basemap builds them). The layers are CARTO's, unchanged. CARTO's hosted copy
  of this style moved to its Protomaps tiles on 21 Oct 2026; nothing here reads CARTO.
- Tiles: OpenStreetMap data (ODbL) in the OpenMapTiles schema, built with Planetiler.
  Credits on the map: © OpenStreetMap contributors, © OpenMapTiles, © CARTO.
- Glyphs: built from Montserrat, Open Sans and Noto Sans (SIL OFL 1.1); see
  tools/basemap/fonts.json.
- Sprite: the style's one icon, the circle-11 city dot, drawn by
  tools/basemap/build-sprite.py.

CARTO's LICENSE.md at that commit follows.

---

Copyright (c) 2018, CartoDB Inc.
All rights reserved.

# Code license: BSD 3-Clause License

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

* Neither the name of the copyright holder nor the names of its
  contributors may be used to endorse or promote products derived from
  this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

# Design license: CC-BY 4.0

The visual design features of the style (also known as the "look and feel" of
the map) are licensed under the Creative Commons Attribution 4.0 license.

To view a copy of the license, visit http://creativecommons.org/licenses/by/4.0/.

Attribution for the design defined in this repository needs not to be provided
on map images, but should be reasonably accessible from maps based on this style
(for example, in a webpage linked from copyright notice on the map).

Products or services using maps derived from OpenMapTiles schema need to visibly
credit "OpenMapTiles.org" or reference "OpenMapTiles" with a link to
http://openmaptiles.org/.

Services and products using CARTO basemap styles need to visibly
credit also "CARTO" with a link to https://carto.com/.

For a browsable electronic map based on OpenMapTiles schema, OpenStreetMap data and CARTO styles, the credits should appear in the corner of the map. For example:

[© CARTO](https://carto.com)
[© OpenMapTiles](http://openmaptiles.org/)
[© OpenStreetMap contributors](http://www.openstreetmap.org/copyright)

For printed and static maps a similar attribution should be made in a textual
description near the image, in the same fashion as if you cite a photograph.

Exceptions to the attribution requirement can be in a written form granted by respective copyright holders.
