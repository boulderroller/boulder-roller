import { coordinateAtFraction } from "@/lib/geometry";
import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import type { StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import {
  CLIMB_MAP_STYLE_URL,
  nightLedgerMapStyle,
} from "./climbMapStyle";
import type { GroundClimb } from "@/types";

// maplibre-gl 6 ships as ES modules only; under a bundler its worker URL must be
// named once, as the portal's maps do.
maplibregl.setWorkerUrl(workerUrl);

export default function ObservatoryGround({
  climbs,
  onChoose,
  mode = "observatory",
  fitBox,
  fraction = null,
}: {
  climbs: GroundClimb[];
  onChoose?: (climb: GroundClimb) => void;
  mode?: "observatory" | "climb" | "account";
  fitBox?: { top: number; bottom: number; left: number; right: number };
  fraction?: number | null;
}) {
  const panned = useRef(false);
  const liveMap = useRef<maplibregl.Map>();
  const fitRef = useRef<() => void>();
  const boxRef = useRef(fitBox);
  boxRef.current = fitBox;
  useEffect(() => {
    fitRef.current?.();
  }, [fitBox]);
  const host = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (!host.current) return;
    const abort = new AbortController();
    let map: maplibregl.Map | undefined;
    let disposed = false;
    let resize: ResizeObserver | undefined;
    panned.current = false;
    setReady(false);
    const dispose = () => {
      if (!disposed) {
        disposed = true;
        abort.abort();
        resize?.disconnect();
        liveMap.current = undefined;
        fitRef.current = undefined;
        map?.remove();
      }
    };
    window.addEventListener("pagehide", dispose);
    void fetch(CLIMB_MAP_STYLE_URL, {
      signal: abort.signal,
    })
      .then((r) => {
        if (!r.ok) throw new Error("ground");
        return r.json() as Promise<StyleSpecification>;
      })
      .then((style) => {
        if (disposed || !host.current) return;
        map = new maplibregl.Map({
          container: host.current,
          style: nightLedgerMapStyle(style),
          center: [-75.23, 40.015],
          zoom: 11,
          attributionControl: false,
        });
        liveMap.current = map;
        map.on("movestart", (e) => {
          if (e.originalEvent) panned.current = true;
        });
        if (mode === "climb") map.doubleClickZoom.disable();
        map.on("load", () => {
          if (!map || disposed) return;
          const features = climbs
            .filter(
              (c) =>
                c.geometry?.type === "LineString" &&
                c.geometry.coordinates.length > 1,
            )
            .map((c) => ({
              type: "Feature" as const,
              id: c.id,
              properties: {
                id: c.id,
                holding:
                  mode === "climb" ||
                  Boolean(c.deposited && BigInt(c.deposited) > 0n),
                registered: c.registered === true,
                attested: c.attested === true,
              },
              geometry: c.geometry!,
            }));
          map.addSource("canon", {
            type: "geojson",
            data: { type: "FeatureCollection", features },
          });
          map.addLayer({
            id: "canon-casing",
            type: "line",
            source: "canon",
            filter: ["==", ["get", "holding"], true],
            layout: { "line-cap": "round", "line-join": "round" },
            paint: { "line-color": "#0A3268", "line-width": 7 },
          });
          map.addLayer({
            id: "canon-lines",
            type: "line",
            source: "canon",
            layout: { "line-cap": "round", "line-join": "round" },
            paint: {
              "line-color": [
                "case",
                ["get", "holding"],
                "#5592E2",
                ["get", "attested"],
                "#F1EEE8",
                ["get", "registered"],
                "#9A9488",
                "#6A6660",
              ],
              "line-width": [
                "case",
                ["boolean", ["feature-state", "hover"], false],
                5,
                2.5,
              ],
            },
          });
          map.addLayer({
            id: "canon-hit",
            type: "line",
            source: "canon",
            paint: { "line-width": 20, "line-opacity": 0 },
          });
          map.addSource("starts", {
            type: "geojson",
            data: {
              type: "FeatureCollection",
              features: features
                .filter((f) => f.properties.holding)
                .map((f) => ({
                  ...f,
                  geometry: {
                    type: "Point" as const,
                    coordinates: f.geometry.coordinates[0],
                  },
                })),
            },
          });
          map.addLayer({
            id: "canon-starts",
            type: "circle",
            source: "starts",
            paint: { "circle-radius": 3, "circle-color": "#F1EEE8" },
          });
          const bounds = new maplibregl.LngLatBounds();
          const fitted = mode === "account" && features.some(f=>f.properties.attested) ? features.filter(f=>f.properties.attested) : features;
          for (const f of fitted)
            for (const p of f.geometry.coordinates)
              if (p.length >= 2 && p.every(Number.isFinite))
                bounds.extend([p[0], p[1]]);
          const fit = () => {
            if (!map || bounds.isEmpty() || panned.current) return;
            const w = map.getContainer().clientWidth,
              h = map.getContainer().clientHeight,
              phone = w < 700;
            const boxWidth = phone ? w : w - 440,
              padding = boxWidth * (mode === "account" ? 0.15 : 0.08);
            map.fitBounds(bounds, {
              padding:
                mode === "climb" && boxRef.current
                  ? {
                      ...boxRef.current,
                      // At maximum sheet height retain a small, valid map fit box.
                      top: Math.max(
                        0,
                        Math.min(
                          boxRef.current.top,
                          h - boxRef.current.bottom - 40,
                        ),
                      ),
                    }
                  : {
                      left: (phone ? 0 : 440) + padding,
                      right: padding,
                      top: phone ? 80 : h * 0.08,
                      bottom: phone ? 180 : h * 0.08,
                    },
              duration: 0,
            });
          };
          fitRef.current = fit;
          fit();
          map.on("resize", fit);
          resize = new ResizeObserver(() => {
            map?.resize();
          });
          resize.observe(host.current!);
          if (mode === "climb") {
            map.on("dblclick", () => {
              panned.current = false;
              fit();
            });
            for (const [index, label] of [
              [0, "Start"],
              [-1, "Finish"],
            ] as const) {
              const point = features[0]?.geometry.coordinates.at(index);
              if (!point) continue;
              const marker = document.createElement("div");
              marker.className = "climb-endpoint";
              marker.textContent = label;
              new maplibregl.Marker({
                element: marker,
                anchor: index === 0 ? "left" : "right",
              })
                .setLngLat([point[0], point[1]])
                .addTo(map);
            }
            map.addSource("inspection", {
              type: "geojson",
              data: { type: "FeatureCollection", features: [] },
            });
            map.addLayer({
              id: "inspection",
              type: "circle",
              source: "inspection",
              paint: {
                "circle-radius": 5,
                "circle-color": "#5592E2",
                "circle-stroke-color": "#F1EEE8",
                "circle-stroke-width": 2,
              },
            });
          }
          let active: string | undefined;
          const choose = (event: maplibregl.MapLayerMouseEvent) => {
            const id = event.features?.[0]?.properties?.id;
            if (active)
              map?.setFeatureState(
                { source: "canon", id: active },
                { hover: false },
              );
            active = id;
            if (id) {
              map?.setFeatureState({ source: "canon", id }, { hover: true });
              const c = climbs.find((c) => c.id === id);
              if (c) onChoose?.(c);
            }
          };
          map.on("mousemove", "canon-hit", (e) => {
            if (map) map.getCanvas().style.cursor = "pointer";
            choose(e);
          });
          map.on("click", "canon-hit", choose);
          map.on("mouseleave", "canon-hit", () => {
            if (map) map.getCanvas().style.cursor = "";
          });
          setReady(true);
        });
      })
      .catch((error) => {
        if (!disposed) console.error("Observatory ground failed", error);
      });
    return () => {
      window.removeEventListener("pagehide", dispose);
      dispose();
    };
  }, [climbs, onChoose, mode]);
  useEffect(() => {
    const source = liveMap.current?.getSource("inspection") as
      maplibregl.GeoJSONSource | undefined;
    const coordinates = climbs[0]?.geometry?.coordinates;
    if (!source || !coordinates) return;
    const point =
      fraction == null ? null : coordinateAtFraction(coordinates, fraction);
    source.setData({
      type: "FeatureCollection",
      features:
        point === null
          ? []
          : [
              {
                type: "Feature",
                properties: {},
                geometry: { type: "Point", coordinates: point },
              },
            ],
    });
  }, [fraction, ready, climbs]);
  return (
    <div
      className="observatory-ground"
      role="region"
      aria-label={mode === "climb" ? "Climb map" : "Climbs"}
      data-ground-ready={ready}
    >
      <div ref={host} className="observatory-ground-canvas" />
      {mode === "climb" ? (
        <>
          <div className="climb-north" aria-hidden="true">
            ↑<br />N
          </div>
          <div className="climb-map-controls">
            <button
              aria-label="Expand map"
              onClick={(e) => {
                void e.currentTarget
                  .closest(".observatory-ground")
                  ?.requestFullscreen();
              }}
            >
              ⤢
            </button>
            <button
              aria-label="Zoom in"
              onClick={() => {
                panned.current = true;
                liveMap.current?.zoomIn();
              }}
            >
              +
            </button>
            <button
              aria-label="Zoom out"
              onClick={() => {
                panned.current = true;
                liveMap.current?.zoomOut();
              }}
            >
              −
            </button>
          </div>
        </>
      ) : null}
    </div>
  );
}
