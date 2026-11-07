'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent, PointerEvent, ReactNode, MutableRefObject } from 'react'
import data from '../data/wises-inspection.json'
import {
  coverPoint,
  nearestRoutePosition,
  pointAtPosition,
  stepIndex,
  settleRoutePosition,
} from '../lib/climb-inspection.mjs'

type Point = [number, number]
type Frame =
  | 'terrain'
  | 'mapDesktop'
  | 'mapMobile'
  | 'profileDesktop'
  | 'profileMobile'
const samples = data.samples
const hoverAcquireRadius = 24
const hoverReleaseRadius = 48
const terrainSizes =
  '(max-width: 760px) 100vw, (min-width: 1605px) 1460px, 91vw'
const terrainSet = (format: string) =>
  [968, 1584, 3080]
    .map((width) => `/terrain/wises-69415757-${width}.${format} ${width}w`)
    .join(', ')

function InspectionLayer({
  frame,
  mobile,
  selected,
  onInspect,
  onPin,
  onLeave,
  activeFrame,
}: {
  frame: Frame
  mobile: boolean
  selected: number | null
  onInspect: (position: number, frame: Frame, immediate?: boolean) => void
  onPin: () => void
  onLeave: (frame: Frame) => void
  activeFrame: MutableRefObject<Frame | null>
}) {
  const svg = useRef<SVGSVGElement>(null)
  const dragging = useRef(false)
  const hoverPosition = useRef<number | null>(null)
  const dragPosition = useRef<number | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [size, setSize] = useState<Point>([0, 0])
  useEffect(() => {
    const element = svg.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => {
      setSize([entry.contentRect.width, entry.contentRect.height])
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  const points = useMemo(() => {
    const source = data.frames[frame]
    return samples.map((sample) => {
      const point = sample[frame] as Point
      return frame === 'terrain'
        ? coverPoint(
            [point[0] * source.width, point[1] * source.height],
            [source.width, source.height],
            size,
            mobile ? [0.52, 0.45] : [0.5, 0.5],
          )
        : ([point[0] * size[0], point[1] * size[1]] as Point)
    })
  }, [frame, mobile, size])
  const path = useMemo(
    () => points.map((p, i) => `${i ? 'L' : 'M'}${p[0]},${p[1]}`).join(' '),
    [points],
  )
  const point = selected == null ? null : pointAtPosition(points, selected)

  useEffect(() => {
    const element = svg.current
    if (!element) return
    function releaseHover() {
      if (hoverPosition.current == null) return
      hoverPosition.current = null
      onLeave(frame)
    }
    function inspectHover(event: globalThis.PointerEvent) {
      if (event.pointerType !== 'mouse' || dragging.current) return
      if (activeFrame.current !== frame) {
        hoverPosition.current = null
      }
      const enteredFrame = (event.target as Element).closest?.('.inspection-layer')
      if (enteredFrame && enteredFrame !== element) {
        releaseHover()
        return
      }
      const attached = hoverPosition.current != null
      if (!attached && !element!.contains(event.target as Node)) return
      const rect = element!.getBoundingClientRect()
      const pointer: Point = [event.clientX - rect.left, event.clientY - rect.top]
      const position = nearestRoutePosition(
        points,
        pointer,
        attached ? hoverReleaseRadius : hoverAcquireRadius,
        hoverPosition.current,
      )
      if (position == null) releaseHover()
      else {
        hoverPosition.current = position
        onInspect(position, frame)
      }
    }
    function leavePage(event: globalThis.PointerEvent) {
      if (event.relatedTarget == null && !dragging.current) releaseHover()
    }
    function keyboardInput(event: globalThis.KeyboardEvent) {
      if (['Shift', 'Control', 'Alt', 'Meta'].includes(event.key)) return
      releaseHover()
    }
    document.addEventListener('pointermove', inspectHover, { passive: true })
    document.addEventListener('pointerout', leavePage)
    document.addEventListener('pointerdown', releaseHover)
    document.addEventListener('keydown', keyboardInput)
    window.addEventListener('blur', releaseHover)
    return () => {
      document.removeEventListener('pointermove', inspectHover)
      document.removeEventListener('pointerout', leavePage)
      document.removeEventListener('pointerdown', releaseHover)
      document.removeEventListener('keydown', keyboardInput)
      window.removeEventListener('blur', releaseHover)
      releaseHover()
    }
  }, [points, frame, onInspect, onLeave, activeFrame])

  function inspect(event: PointerEvent<SVGSVGElement>, radius = Infinity) {
    const rect = event.currentTarget.getBoundingClientRect()
    const pointer: Point = [event.clientX - rect.left, event.clientY - rect.top]
    const position = nearestRoutePosition(
      points,
      pointer,
      radius,
      dragPosition.current,
    )
    if (position != null) {
      dragPosition.current = position
      onInspect(position, frame, event.pointerType !== 'mouse')
    }
    return position
  }
  return (
    <svg
      ref={svg}
      className={`inspection-layer ${frame === 'terrain' ? 'terrain-layer' : ''}`}
      aria-hidden="true"
      data-frame={frame}
      data-dragging={isDragging}
      data-sample-index={selected == null ? '' : Math.round(selected)}
      data-route-position={selected ?? ''}
      viewBox={`0 0 ${size[0] || 1} ${size[1] || 1}`}
      onPointerDown={(event) => {
        if (event.button !== 0) return
        dragging.current = true
        dragPosition.current = hoverPosition.current
        setIsDragging(true)
        event.currentTarget.setPointerCapture(event.pointerId)
        inspect(event)
        onPin()
        const control = event.currentTarget
          .closest('.climb-experience')
          ?.querySelector<HTMLElement>('[role="slider"]')
        control?.focus({ preventScroll: true })
        // Keep the subsequent mouse default from blurring the focused slider.
        event.preventDefault()
      }}
      onPointerMove={(event) => {
        if (dragging.current) inspect(event)
      }}
      onPointerUp={(event) => {
        dragging.current = false
        setIsDragging(false)
        hoverPosition.current = event.pointerType === 'mouse'
          ? inspect(event, hoverReleaseRadius)
          : null
        if (event.currentTarget.hasPointerCapture(event.pointerId))
          event.currentTarget.releasePointerCapture(event.pointerId)
      }}
      onPointerCancel={(event) => {
        dragging.current = false
        hoverPosition.current = null
        setIsDragging(false)
        if (event.currentTarget.hasPointerCapture(event.pointerId))
          event.currentTarget.releasePointerCapture(event.pointerId)
        onLeave(frame)
      }}
    >
      <path d={path} className="inspection-hit" />
      {point ? (
        <g className="inspection-marker">
          {frame.startsWith('profile') ? (
            <line
              x1={point[0]}
              x2={point[0]}
              y1={size[1] * 0.12}
              y2={size[1] * 0.77}
              className="profile-guide"
            />
          ) : null}
          <circle
            cx={point[0]}
            cy={point[1]}
            r={frame === 'terrain' ? 16 : 11}
            className="marker-halo"
          />
          <circle
            cx={point[0]}
            cy={point[1]}
            r={frame === 'terrain' ? 6 : 4.5}
            className="marker-point"
          />
        </g>
      ) : null}
    </svg>
  )
}

export default function ClimbExplorer({ children }: { children: ReactNode }) {
  const [selected, setSelected] = useState<number | null>(null)
  const [mobile, setMobile] = useState(false)
  const [input, setInput] = useState<'keyboard' | 'pointer'>('keyboard')
  const inputRef = useRef<'keyboard' | 'pointer'>('keyboard')
  const control = useRef<HTMLDivElement>(null)
  const pinned = useRef(false)
  const keyboardFocused = useRef(false)
  const inspectedFrame = useRef<Frame | null>(null)
  const displayed = useRef<number | null>(null)
  const target = useRef<number | null>(null)
  const animation = useRef<number | null>(null)
  const reducedMotion = useRef(false)
  const moveTo = useCallback((position: number | null, immediate = false) => {
    target.current = position
    if (position == null || displayed.current == null || immediate || reducedMotion.current) {
      if (animation.current != null) cancelAnimationFrame(animation.current)
      animation.current = null
      displayed.current = position
      setSelected(position)
      return
    }
    // Pointer events only update the target; one frame loop owns all three views.
    if (animation.current != null) return
    let previousTime: number | null = null
    function settle(time: number) {
      if (displayed.current == null || target.current == null) return
      const next = settleRoutePosition(
        displayed.current, target.current,
        previousTime == null ? 16 : time - previousTime,
      )
      previousTime = time
      displayed.current = next
      setSelected(next)
      animation.current = next === target.current ? null : requestAnimationFrame(settle)
    }
    animation.current = requestAnimationFrame(settle)
  }, [])
  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)')
    const update = () => {
      reducedMotion.current = query.matches
      if (query.matches) moveTo(target.current, true)
    }
    update()
    query.addEventListener('change', update)
    return () => {
      query.removeEventListener('change', update)
      if (animation.current != null) cancelAnimationFrame(animation.current)
    }
  }, [moveTo])
  const onInspect = useCallback((position: number, frame: Frame, immediate = false) => {
    inspectedFrame.current = frame
    moveTo(position, immediate)
  }, [moveTo])
  const onPin = useCallback(() => {
    pinned.current = true
  }, [])
  const onLeave = useCallback((frame: Frame) => {
    if (inspectedFrame.current !== frame) return
    inspectedFrame.current = null
    // Leaving the corridor detaches the pointer, but keeps the inspected place.
  }, [])
  useEffect(() => {
    function keyboardInput(event: globalThis.KeyboardEvent) {
      if (['Shift', 'Control', 'Alt', 'Meta'].includes(event.key)) return
      inputRef.current = 'keyboard'
      setInput('keyboard')
      keyboardFocused.current = document.activeElement === control.current
    }
    document.addEventListener('keydown', keyboardInput, true)
    return () => document.removeEventListener('keydown', keyboardInput, true)
  }, [])
  useEffect(() => {
    const query = window.matchMedia('(max-width: 760px)')
    const update = () => setMobile(query.matches)
    update()
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])
  const sample = selected == null ? null : samples[Math.round(selected)]
  const value = sample ?? samples[0]
  const climbDistance = ((value.d - samples[0].d) / 1000).toFixed(2)
  const description = `${climbDistance} kilometers from the start of the climb, ${value.elevation.toFixed(1)} meters elevation`
  const layerProps = {
    mobile,
    selected,
    onInspect,
    onPin,
    onLeave,
    activeFrame: inspectedFrame,
  }
  function keyDown(event: KeyboardEvent<HTMLDivElement>) {
    const steps: Record<string, number> = {
      ArrowRight: 1,
      ArrowUp: 1,
      ArrowLeft: -1,
      ArrowDown: -1,
      PageUp: 10,
      PageDown: -10,
    }
    if (event.key === 'Escape') {
      pinned.current = false
      moveTo(null, true)
    } else if (event.key === 'Home' || event.key === 'End') {
      moveTo(event.key === 'Home' ? 0 : samples.length - 1, true)
    } else if (event.key in steps) {
      moveTo(stepIndex(displayed.current, steps[event.key], samples.length), true)
    } else return
    event.preventDefault()
  }
  return (
    <div
      className="climb-experience"
      data-input={input}
      data-selected-sample={selected == null ? '' : Math.round(selected)}
      onPointerDownCapture={(event) => {
        if (event.button !== 0) return
        inputRef.current = 'pointer'
        setInput('pointer')
        keyboardFocused.current = false
      }}
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          pinned.current = false
          moveTo(null, true)
        }
      }}
      onPointerDown={(event) => {
        if (
          !(event.target as Element).closest('.inspection-hit, [role="slider"]')
        ) {
          pinned.current = false
          moveTo(null, true)
        }
      }}
    >
      {children}
      <div className="terrain-frame">
        <picture>
          <source
            type="image/avif"
            srcSet={terrainSet('avif')}
            sizes={terrainSizes}
          />
          <source
            type="image/webp"
            srcSet={terrainSet('webp')}
            sizes={terrainSizes}
          />
          <img
            className="terrain"
            src="/terrain/wises-69415757-1584.webp"
            width={3080}
            height={2170}
            sizes={terrainSizes}
            alt=""
            fetchPriority="high"
          />
        </picture>
        <InspectionLayer frame="terrain" {...layerProps} />
        <p className="terrain-caption">
          Wises Mill Road · 1.16 km
        </p>
      </div>
      <figure
        className="ride-inset"
        aria-label="Wises Mill Road and its place in the recorded ride"
      >
        <div className="climb-caption">
          <span id="climb-name">Wises Mill Road</span>
          <output className="climb-readout" aria-hidden="true">
            {sample
              ? `${climbDistance} km · ${sample.elevation.toFixed(0)} m`
              : '1.16 km'}
          </output>
        </div>
        <div
          ref={control}
          className="segment-map"
          role="slider"
          tabIndex={0}
          aria-label="Explore Wises Mill Road"
          aria-describedby="climb-instructions"
          aria-valuemin={0}
          aria-valuemax={samples.length - 1}
          aria-valuenow={selected == null ? 0 : Math.round(selected)}
          aria-valuetext={description}
          onKeyDown={keyDown}
          onFocus={() => {
            keyboardFocused.current = inputRef.current === 'keyboard'
            if (keyboardFocused.current) moveTo(displayed.current ?? 0, true)
          }}
          onBlur={() => {
            keyboardFocused.current = false
            if (!pinned.current && inputRef.current === 'keyboard') moveTo(null, true)
          }}
        >
          <picture>
            <source
              media="(max-width: 760px)"
              srcSet="/terrain/wises-map-mobile.webp"
              width={680}
              height={276}
            />
            <img
              src="/terrain/wises-map-desktop.webp"
              width={608}
              height={161}
              alt="Wises Mill Road in Philadelphia, with the recorded climb highlighted and both endpoints marked."
            />
          </picture>
          <InspectionLayer
            frame={mobile ? 'mapMobile' : 'mapDesktop'}
            {...layerProps}
          />
        </div>
        <div className="profile-frame">
          <picture>
            <source
              media="(max-width: 760px)"
              srcSet="/terrain/ride-elevation-mobile.webp"
              width={800}
              height={250}
            />
            <img
              className="elevation"
              src="/terrain/ride-elevation.webp"
              width={1500}
              height={240}
              alt="Elevation over the full 128.7 kilometer ride, with Wises Mill Road highlighted from 49.13 to 50.29 kilometers. Gaps in the recording remain gaps."
            />
          </picture>
          <InspectionLayer
            frame={mobile ? 'profileMobile' : 'profileDesktop'}
            {...layerProps}
          />
        </div>
        <figcaption className="map-footer">
          <span id="climb-instructions">
            Drag the climb · arrow keys to explore
          </span>
          <span className="map-attribution">
            <a href="https://carto.com/attribution/">© CARTO</a>,{' '}
            <a href="https://www.openstreetmap.org/copyright">
              © OpenStreetMap contributors
            </a>
          </span>
        </figcaption>
      </figure>
    </div>
  )
}
