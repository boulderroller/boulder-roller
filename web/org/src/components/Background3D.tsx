'use client'

import { useRef, useMemo } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import * as THREE from 'three'

function Boulder({
  startX,
  y,
  z,
  scale,
  speed,
  color,
  seed,
}: {
  startX: number
  y: number
  z: number
  scale: number
  speed: number
  color: string
  seed: number
}) {
  const meshRef = useRef<THREE.Mesh>(null)
  const timeOffset = useMemo(() => seed * 50, [seed])

  const geometry = useMemo(() => {
    const geo = new THREE.DodecahedronGeometry(1, 0)
    const positions = geo.attributes.position
    const rng = (i: number) => Math.sin(seed * 100 + i * 73.7) * 0.5 + 0.5

    for (let i = 0; i < positions.count; i++) {
      const x = positions.getX(i)
      const y = positions.getY(i)
      const z = positions.getZ(i)
      const noise = 0.1 * rng(i)
      positions.setXYZ(
        i,
        x * (1 + noise * 0.25),
        y * (1 + noise * 0.15),
        z * (1 + noise * 0.25)
      )
    }

    geo.computeVertexNormals()
    return geo
  }, [seed])

  useFrame((state) => {
    if (!meshRef.current) return
    const t = state.clock.elapsedTime + timeOffset

    const xRange = 28
    let x = startX - (t * speed) % xRange
    if (x < -14) x += xRange

    meshRef.current.position.x = x

    const circumference = scale * 2 * Math.PI
    const rotationPerUnit = (Math.PI * 2) / circumference
    meshRef.current.rotation.z = -(t * speed) * rotationPerUnit * 0.4
  })

  return (
    <mesh ref={meshRef} geometry={geometry} scale={scale} position={[startX, y, z]}>
      <meshStandardMaterial
        color={color}
        roughness={0.92}
        metalness={0.08}
        flatShading
      />
    </mesh>
  )
}

function Scene() {
  return (
    <>
      {/* Late afternoon sun */}
      <directionalLight position={[10, 8, 5]} intensity={1.3} color="#e0b060" />
      <ambientLight intensity={0.2} color="#b09070" />
      <directionalLight position={[-8, 4, 3]} intensity={0.12} color="#8090a0" />

      {/* Far background - very slow */}
      <Boulder startX={12} y={0.2} z={-14} scale={5} speed={0.04} color="#3a332b" seed={1} />
      <Boulder startX={-4} y={0.6} z={-16} scale={6} speed={0.03} color="#332d26" seed={2} />

      {/* Mid distance */}
      <Boulder startX={9} y={-0.6} z={-7} scale={3.8} speed={0.1} color="#4a4238" seed={3} />
      <Boulder startX={-2} y={-0.3} z={-8} scale={3} speed={0.08} color="#45403a" seed={4} />

      {/* Foreground - slow but closer */}
      <Boulder startX={7} y={-1.8} z={-2.5} scale={4.8} speed={0.14} color="#5a5248" seed={5} />
      <Boulder startX={-5} y={-2} z={-1.5} scale={5.5} speed={0.12} color="#524a40" seed={6} />
    </>
  )
}

export default function Background3D() {
  return (
    <div className="fixed inset-0 -z-10 overflow-hidden">
      {/* Desert twilight sky */}
      <div
        className="absolute inset-0"
        style={{
          background: `linear-gradient(
            to bottom,
            #18140f 0%,
            #221c16 20%,
            #302820 40%,
            #3d342a 55%,
            #4a4035 70%,
            #574c40 85%,
            #635848 100%
          )`,
        }}
      />

      {/* Horizon warmth */}
      <div
        className="absolute inset-0"
        style={{
          background: `radial-gradient(ellipse 200% 35% at 50% 100%, rgba(160, 120, 70, 0.18) 0%, transparent 65%)`,
        }}
      />

      {/* Three.js */}
      <Canvas
        camera={{ position: [0, 0.5, 8], fov: 50 }}
        dpr={[1, 2]}
        gl={{ antialias: true, alpha: true, powerPreference: 'high-performance' }}
        style={{ background: 'transparent', position: 'absolute', inset: 0 }}
      >
        <fog attach="fog" args={['#302820', 6, 28]} />
        <Scene />
      </Canvas>

      {/* Ground haze */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background: `linear-gradient(to top, rgba(75, 65, 50, 0.35) 0%, rgba(75, 65, 50, 0.08) 25%, transparent 45%)`,
        }}
      />

      {/* Vignette */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background: `radial-gradient(ellipse 85% 75% at 50% 50%, transparent 0%, rgba(15, 12, 10, 0.55) 100%)`,
        }}
      />

      {/* Grain */}
      <div className="noise-overlay" />
    </div>
  )
}
