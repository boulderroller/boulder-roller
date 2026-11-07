'use client'

export default function Background() {
  return (
    <div className="fixed inset-0 overflow-hidden pointer-events-none" aria-hidden="true">
      {/* Deep void gradient base */}
      <div
        className="absolute inset-0"
        style={{
          background: `
            radial-gradient(ellipse 80% 60% at 50% 120%, rgba(90, 69, 16, 0.15) 0%, transparent 60%),
            radial-gradient(ellipse 60% 40% at 20% 80%, rgba(139, 105, 20, 0.1) 0%, transparent 50%),
            radial-gradient(ellipse 50% 50% at 80% 20%, rgba(200, 155, 92, 0.08) 0%, transparent 50%),
            #0a0a0a
          `
        }}
      />

      {/* Rolling spheres */}
      {/* Large sphere - bottom left */}
      <div
        className="sphere sphere-1"
        style={{
          width: '500px',
          height: '500px',
          left: '-10%',
          bottom: '-20%',
          opacity: 0.7,
        }}
      />

      {/* Medium sphere - top right */}
      <div
        className="sphere sphere-2"
        style={{
          width: '350px',
          height: '350px',
          right: '-5%',
          top: '5%',
          opacity: 0.6,
        }}
      />

      {/* Small sphere - center left */}
      <div
        className="sphere sphere-3"
        style={{
          width: '200px',
          height: '200px',
          left: '15%',
          top: '30%',
          opacity: 0.5,
        }}
      />

      {/* Tiny sphere - bottom right */}
      <div
        className="sphere sphere-4"
        style={{
          width: '120px',
          height: '120px',
          right: '20%',
          bottom: '25%',
          opacity: 0.4,
        }}
      />

      {/* Extra small - top center */}
      <div
        className="sphere sphere-5"
        style={{
          width: '80px',
          height: '80px',
          left: '55%',
          top: '15%',
          opacity: 0.35,
        }}
      />

      {/* Subtle vignette */}
      <div
        className="absolute inset-0"
        style={{
          background: 'radial-gradient(ellipse at center, transparent 0%, rgba(0, 0, 0, 0.4) 100%)',
        }}
      />

      {/* Noise overlay */}
      <div className="noise-overlay" />
    </div>
  )
}
