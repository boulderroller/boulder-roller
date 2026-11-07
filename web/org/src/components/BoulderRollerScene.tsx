'use client'

import { useEffect, useRef } from 'react';
import * as THREE from 'three';

export default function BoulderRollerScene() {
  const containerRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<boolean>(false);

  useEffect(() => {
    if (!containerRef.current || sceneRef.current) return;
    sceneRef.current = true;

    const scene = new THREE.Scene();
    let renderer: THREE.WebGLRenderer;
    let animationFrameId = 0;
    let disposed = false;

    const getPixelRatio = () => {
      const cap = window.innerWidth < 768 ? 1.2 : 1.5;
      return Math.min(window.devicePixelRatio || 1, cap);
    };

    try {
      renderer = new THREE.WebGLRenderer({
        antialias: true,
        powerPreference: 'high-performance',
      });
      renderer.setPixelRatio(getPixelRatio());
      renderer.setSize(containerRef.current.clientWidth, containerRef.current.clientHeight);
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.12;
      containerRef.current.appendChild(renderer.domElement);
    } catch (error) {
      console.warn('BoulderRollerScene: WebGL renderer unavailable, using static fallback.', error);
      sceneRef.current = false;
      return;
    }

    const handleContextLost = (event: Event) => {
      event.preventDefault();
      disposed = true;
      cancelAnimationFrame(animationFrameId);
      console.warn('BoulderRollerScene: WebGL context lost, retaining static fallback.');
    };

    renderer.domElement.addEventListener('webglcontextlost', handleContextLost);

    // High-res sky, capped on small screens to reduce GPU memory pressure.
    const SKY_SIZE = window.innerWidth < 768 ? 2048 : 4096;
    const bgCanvas = document.createElement('canvas');
    bgCanvas.width = SKY_SIZE;
    bgCanvas.height = SKY_SIZE;
    const bgCtx = bgCanvas.getContext('2d')!;

    // Pure black void
    bgCtx.fillStyle = '#010101';
    bgCtx.fillRect(0, 0, SKY_SIZE, SKY_SIZE);

    // Milky way band
    bgCtx.save();
    bgCtx.translate(SKY_SIZE / 2, SKY_SIZE * 0.4);
    bgCtx.rotate(-0.35);

    const inBand = (y: number, width: number) => {
      return Math.exp(-(y * y) / (2 * width * width));
    };

    const S = SKY_SIZE / 512; // 8x scale

    // 80000 sub-pixel stars for dense milky way
    for (let i = 0; i < 80000; i++) {
      const x = (Math.random() - 0.5) * 700 * S;
      const y = (Math.random() - 0.5) * 500 * S;

      const density = inBand(y, 120 * S);
      if (Math.random() > density) continue;

      const brightness = Math.random() * 0.4 + 0.1;
      const temp = Math.random();
      // Star color temperature variation
      const r = temp > 0.7 ? 255 : (temp > 0.3 ? 240 + Math.random() * 15 : 220 + Math.random() * 20);
      const g = temp > 0.7 ? 240 + Math.random() * 15 : (temp > 0.3 ? 230 + Math.random() * 20 : 225 + Math.random() * 25);
      const b = temp > 0.7 ? 200 + Math.random() * 30 : (temp > 0.3 ? 220 + Math.random() * 30 : 240 + Math.random() * 15);

      bgCtx.fillStyle = `rgba(${r}, ${g}, ${b}, ${brightness})`;
      bgCtx.fillRect(x, y, 1, 1);
    }

    // Core region - very dense
    for (let i = 0; i < 35000; i++) {
      const x = (Math.random() - 0.5) * 500 * S;
      const y = (Math.random() - 0.5) * 200 * S;

      const density = inBand(y, 60 * S);
      if (Math.random() > density) continue;

      const brightness = Math.random() * 0.35 + 0.15;
      const r = 245 + Math.random() * 10;
      const g = 235 + Math.random() * 15;
      const b = 210 + Math.random() * 25;

      bgCtx.fillStyle = `rgba(${r}, ${g}, ${b}, ${brightness})`;
      bgCtx.fillRect(x, y, 1, 1);
    }

    bgCtx.restore();

    // Scattered field stars
    for (let i = 0; i < 3000; i++) {
      const x = Math.random() * SKY_SIZE;
      const y = Math.random() * SKY_SIZE;
      const brightness = Math.random() * 0.12 + 0.02;
      bgCtx.fillStyle = `rgba(230, 225, 215, ${brightness})`;
      bgCtx.fillRect(x, y, 1, 1);
    }

    const bgTexture = new THREE.CanvasTexture(bgCanvas);
    scene.background = bgTexture;

    // Twinkling star layer - separate sprites that animate
    interface TwinkleStar {
      x: number;
      y: number;
      baseAlpha: number;
      phase: number;
      speed: number;
      color: { r: number; g: number; b: number };
    }

    const twinkleStars: TwinkleStar[] = [];
    const twinkleCanvas = document.createElement('canvas');
    twinkleCanvas.width = SKY_SIZE;
    twinkleCanvas.height = SKY_SIZE;
    const twinkleCtx = twinkleCanvas.getContext('2d')!;

    // Create twinkling stars - brighter ones that shimmer
    for (let i = 0; i < 800; i++) {
      const inMilkyWay = Math.random() > 0.4;
      let x, y;

      if (inMilkyWay) {
        // Position in milky way band
        const angle = -0.35;
        const bx = (Math.random() - 0.5) * 600 * S;
        const by = (Math.random() - 0.5) * 300 * S;
        x = SKY_SIZE / 2 + bx * Math.cos(angle) - by * Math.sin(angle);
        y = SKY_SIZE * 0.4 + bx * Math.sin(angle) + by * Math.cos(angle);
      } else {
        x = Math.random() * SKY_SIZE;
        y = Math.random() * SKY_SIZE;
      }

      // Color temperature - blue-white to warm yellow
      const temp = Math.random();
      const color = temp > 0.6
        ? { r: 255, g: 252, b: 245 }  // Hot white
        : temp > 0.3
        ? { r: 255, g: 248, b: 220 }  // Warm white
        : { r: 200, g: 220, b: 255 }; // Blue-white

      twinkleStars.push({
        x,
        y,
        baseAlpha: Math.random() * 0.5 + 0.4,
        phase: Math.random() * Math.PI * 2,
        speed: Math.random() * 2 + 1,
        color,
      });
    }

    const twinkleTexture = new THREE.CanvasTexture(twinkleCanvas);

    // Function to update twinkling
    const updateTwinkle = (t: number) => {
      twinkleCtx.clearRect(0, 0, SKY_SIZE, SKY_SIZE);

      twinkleStars.forEach(star => {
        // Multi-frequency scintillation like real atmospheric turbulence
        const flicker1 = Math.sin(t * star.speed + star.phase);
        const flicker2 = Math.sin(t * star.speed * 2.3 + star.phase * 1.7) * 0.5;
        const flicker3 = Math.sin(t * star.speed * 5.1 + star.phase * 0.3) * 0.25;
        const flicker = (flicker1 + flicker2 + flicker3) / 1.75;

        const alpha = star.baseAlpha * (0.5 + flicker * 0.5);

        if (alpha > 0.1) {
          // Sharp point with tiny diffraction spikes
          const { r, g, b } = star.color;

          // Core - sharp point
          twinkleCtx.fillStyle = `rgba(${r}, ${g}, ${b}, ${alpha})`;
          twinkleCtx.fillRect(star.x, star.y, 1, 1);

          // Subtle cross diffraction pattern on brightest
          if (alpha > 0.6) {
            const spikeAlpha = (alpha - 0.6) * 0.8;
            twinkleCtx.fillStyle = `rgba(${r}, ${g}, ${b}, ${spikeAlpha * 0.4})`;
            twinkleCtx.fillRect(star.x - 1, star.y, 1, 1);
            twinkleCtx.fillRect(star.x + 1, star.y, 1, 1);
            twinkleCtx.fillRect(star.x, star.y - 1, 1, 1);
            twinkleCtx.fillRect(star.x, star.y + 1, 1, 1);
          }
        }
      });

      twinkleTexture.needsUpdate = true;
    };

    // Combine base sky + twinkle layer using additive blend
    const skyScene = new THREE.Scene();
    const skyCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

    // Background quad
    const skyGeo = new THREE.PlaneGeometry(2, 2);
    const skyMat = new THREE.ShaderMaterial({
      uniforms: {
        tBase: { value: bgTexture },
        tTwinkle: { value: twinkleTexture },
      },
      vertexShader: `
        varying vec2 vUv;
        void main() {
          vUv = uv;
          gl_Position = vec4(position, 1.0);
        }
      `,
      fragmentShader: `
        uniform sampler2D tBase;
        uniform sampler2D tTwinkle;
        varying vec2 vUv;
        void main() {
          vec4 base = texture2D(tBase, vUv);
          vec4 twinkle = texture2D(tTwinkle, vUv);
          gl_FragColor = base + twinkle; // Additive blend
        }
      `,
      depthTest: false,
      depthWrite: false,
    });
    const skyQuad = new THREE.Mesh(skyGeo, skyMat);
    skyScene.add(skyQuad);

    // Render sky to texture for use as scene background
    const skyRenderTarget = new THREE.WebGLRenderTarget(SKY_SIZE, SKY_SIZE);
    scene.background = skyRenderTarget.texture;

    // Darker fog for pitch black void
    scene.fog = new THREE.FogExp2(0x020201, 0.004);

    const camera = new THREE.PerspectiveCamera(
      30,
      containerRef.current.clientWidth / containerRef.current.clientHeight,
      0.1,
      2000
    );
    camera.position.set(0, 20, 90);

    // Boulder glow / aura layer
    const glowCanvas = document.createElement('canvas');
    glowCanvas.style.position = 'absolute';
    glowCanvas.style.top = '0';
    glowCanvas.style.left = '0';
    glowCanvas.style.width = '100%';
    glowCanvas.style.height = '100%';
    glowCanvas.style.pointerEvents = 'none';
    glowCanvas.style.mixBlendMode = 'screen';
    glowCanvas.style.opacity = '0.5';
    containerRef.current.appendChild(glowCanvas);

    const glowCtx = glowCanvas.getContext('2d')!;

    const drawBoulderGlow = (boulderList: THREE.Mesh[], cam: THREE.Camera, mx: number, my: number) => {
      const w = glowCanvas.width;
      const h = glowCanvas.height;

      glowCtx.clearRect(0, 0, w, h);

      boulderList.forEach(b => {
        if (b.userData.falling) return;

        // Project boulder position to screen space
        const pos = b.position.clone();
        pos.project(cam);

        // Convert to canvas coords
        const screenX = (pos.x * 0.5 + 0.5) * w;
        const screenY = (-pos.y * 0.5 + 0.5) * h;

        // Skip if behind camera or off screen
        if (pos.z > 1 || screenX < -100 || screenX > w + 100 || screenY < -100 || screenY > h + 100) return;

        // Depth-based size and parallax
        const depth = 1 - pos.z; // 0 = far, 1 = near
        const baseSize = b.userData.baseRadius * 20 * depth;

        // Parallax offset - closer boulders shift more
        const parallaxX = mx * depth * 25;
        const parallaxY = my * depth * 20;

        // Warm bronze glow halos
        // Outer halo - soft warm atmosphere
        const outer = glowCtx.createRadialGradient(
          screenX + parallaxX * 0.2, screenY + parallaxY * 0.2, 0,
          screenX + parallaxX * 0.2, screenY + parallaxY * 0.2, baseSize * 3.5
        );
        outer.addColorStop(0, 'rgba(80, 60, 40, 0.2)');
        outer.addColorStop(0.4, 'rgba(60, 45, 30, 0.08)');
        outer.addColorStop(1, 'rgba(0, 0, 0, 0)');
        glowCtx.fillStyle = outer;
        glowCtx.fillRect(0, 0, w, h);

        // Inner warm glow
        const inner = glowCtx.createRadialGradient(
          screenX + parallaxX * 0.5, screenY + parallaxY * 0.5, 0,
          screenX + parallaxX * 0.5, screenY + parallaxY * 0.5, baseSize * 1.5
        );
        inner.addColorStop(0, 'rgba(120, 90, 55, 0.25)');
        inner.addColorStop(0.5, 'rgba(90, 70, 45, 0.1)');
        inner.addColorStop(1, 'rgba(0, 0, 0, 0)');
        glowCtx.fillStyle = inner;
        glowCtx.fillRect(0, 0, w, h);
      });
    };

    // Film grain / oxidation overlay
    const grainCanvas = document.createElement('canvas');
    grainCanvas.style.position = 'absolute';
    grainCanvas.style.top = '0';
    grainCanvas.style.left = '0';
    grainCanvas.style.width = '100%';
    grainCanvas.style.height = '100%';
    grainCanvas.style.pointerEvents = 'none';
    grainCanvas.style.mixBlendMode = 'overlay';
    grainCanvas.style.opacity = '0.4';
    containerRef.current.appendChild(grainCanvas);

    const grainCtx = grainCanvas.getContext('2d')!;

    const updateGrain = () => {
      if (!containerRef.current) return;
      grainCanvas.width = containerRef.current.clientWidth;
      grainCanvas.height = containerRef.current.clientHeight;
      glowCanvas.width = containerRef.current.clientWidth;
      glowCanvas.height = containerRef.current.clientHeight;

      const w = grainCanvas.width;
      const h = grainCanvas.height;

      // Vignette
      const vignetteGrad = grainCtx.createRadialGradient(
        w / 2, h / 2, h * 0.18,
        w / 2, h / 2, h * 0.88
      );
      vignetteGrad.addColorStop(0, 'rgba(0, 0, 0, 0)');
      vignetteGrad.addColorStop(0.45, 'rgba(0, 0, 0, 0.1)');
      vignetteGrad.addColorStop(1, 'rgba(0, 0, 0, 0.7)');
      grainCtx.fillStyle = vignetteGrad;
      grainCtx.fillRect(0, 0, w, h);

      // Subtle warm color cast at edges
      const warmGrad = grainCtx.createRadialGradient(
        w / 2, h / 2, h * 0.3,
        w / 2, h / 2, h
      );
      warmGrad.addColorStop(0, 'rgba(0, 0, 0, 0)');
      warmGrad.addColorStop(1, 'rgba(30, 15, 5, 0.3)');
      grainCtx.fillStyle = warmGrad;
      grainCtx.fillRect(0, 0, w, h);
    };

    // Animated grain layer
    const animateGrain = (mx: number, my: number, t: number, boulderList: THREE.Mesh[], cam: THREE.Camera) => {
      const w = grainCanvas.width;
      const h = grainCanvas.height;

      // Clear and redraw vignette
      grainCtx.clearRect(0, 0, w, h);

      // Vignette - stronger
      const vignetteGrad = grainCtx.createRadialGradient(
        w / 2, h / 2, h * 0.18,
        w / 2, h / 2, h * 0.88
      );
      vignetteGrad.addColorStop(0, 'rgba(0, 0, 0, 0)');
      vignetteGrad.addColorStop(0.45, 'rgba(0, 0, 0, 0.15)');
      vignetteGrad.addColorStop(1, 'rgba(0, 0, 0, 0.75)');
      grainCtx.fillStyle = vignetteGrad;
      grainCtx.fillRect(0, 0, w, h);

      // Film grain - sparse for performance
      const grainData = grainCtx.getImageData(0, 0, w, h);
      const pixels = grainData.data;

      for (let i = 0; i < pixels.length; i += 16) {
        const noise = (Math.random() - 0.5) * 25;
        pixels[i] += noise;
        pixels[i + 1] += noise;
        pixels[i + 2] += noise;
      }

      grainCtx.putImageData(grainData, 0, 0);

      // Draw boulder glow
      drawBoulderGlow(boulderList, cam, mx, my);
    };

    updateGrain();

    // Very minimal ambient - pitch black surroundings with warm undertone
    const hemiLight = new THREE.HemisphereLight(0x241a10, 0x020202, 0.5);
    scene.add(hemiLight);

    // Subtle warm ambient fill
    const ambientLight = new THREE.AmbientLight(0x0d0906, 0.36);
    scene.add(ambientLight);

    // Distant starlight - warm gold/bronze tint, subtle
    const starLight = new THREE.DirectionalLight(0xd1aa72, 0.48);
    starLight.position.set(-30, 100, -20);
    scene.add(starLight);

    // Secondary fill - very subtle warm
    const starLight2 = new THREE.DirectionalLight(0xb89860, 0.24);
    starLight2.position.set(40, 60, 30);
    scene.add(starLight2);

    // Soft rim light - warm bronze edge glow
    const rimLight = new THREE.DirectionalLight(0xd2a05e, 0.62);
    rimLight.position.set(0, 30, -100);
    scene.add(rimLight);

    const sideRim = new THREE.DirectionalLight(0x8f6538, 0.32);
    sideRim.position.set(90, 28, 40);
    scene.add(sideRim);

    // Faint top fill
    const topRim = new THREE.DirectionalLight(0x908070, 0.15);
    topRim.position.set(0, 120, 0);
    scene.add(topRim);

    let time = 0;

    const getHeight = (localX: number, localY: number, t: number) => {
      return (
        Math.sin(localX * 0.04 + t * 0.3) * 5 +
        Math.sin(localY * 0.03 - t * 0.2) * 6 +
        Math.sin(localX * 0.02 + localY * 0.02 + t * 0.4) * 4 +
        Math.sin(localX * 0.06 - t * 0.5) * Math.cos(localY * 0.05 + t * 0.25) * 3
      );
    };

    const getWorldHeight = (worldX: number, worldZ: number, t: number) => {
      return getHeight(worldX, -worldZ, t);
    };

    const getWorldGradient = (worldX: number, worldZ: number, t: number) => {
      const eps = 0.5;
      const h = getWorldHeight(worldX, worldZ, t);
      const hX = getWorldHeight(worldX + eps, worldZ, t);
      const hZ = getWorldHeight(worldX, worldZ + eps, t);
      return new THREE.Vector3((hX - h) / eps, 0, (hZ - h) / eps);
    };

    const PLATFORM_SIZE = 80;
    const groundGeo = new THREE.PlaneGeometry(PLATFORM_SIZE * 2.5, PLATFORM_SIZE * 2.5, 100, 100);

    const groundPositions = groundGeo.attributes.position;
    const vertexData: { x: number; y: number }[] = [];
    const colors = new Float32Array(groundPositions.count * 3);

    // Dark warm ground
    const centerColor = new THREE.Color(0x1a1614);
    const midColor = new THREE.Color(0x0c0a08);
    const edgeColor = new THREE.Color(0x040302);

    for (let i = 0; i < groundPositions.count; i++) {
      const x = groundPositions.getX(i);
      const y = groundPositions.getY(i);
      vertexData.push({ x, y });

      const dist = Math.sqrt(x * x + y * y);
      const t = Math.min(1, dist / (PLATFORM_SIZE * 1.2));

      let color;
      if (t < 0.6) {
        color = centerColor.clone().lerp(midColor, t / 0.6);
      } else {
        color = midColor.clone().lerp(edgeColor, (t - 0.6) / 0.4);
      }

      colors[i * 3] = color.r;
      colors[i * 3 + 1] = color.g;
      colors[i * 3 + 2] = color.b;
    }

    groundGeo.setAttribute('color', new THREE.BufferAttribute(colors, 3));

    // Granular noise - medium contrast static
    const noiseSize = 256;
    const noiseCanvas = document.createElement('canvas');
    noiseCanvas.width = noiseSize;
    noiseCanvas.height = noiseSize;
    const noiseCtx = noiseCanvas.getContext('2d')!;
    const noiseData = noiseCtx.createImageData(noiseSize, noiseSize);

    for (let i = 0; i < noiseData.data.length; i += 4) {
      // Medium random variation
      const v = 128 + (Math.random() - 0.5) * 50;
      noiseData.data[i] = v;
      noiseData.data[i + 1] = v;
      noiseData.data[i + 2] = v;
      noiseData.data[i + 3] = 255;
    }
    noiseCtx.putImageData(noiseData, 0, 0);

    const noiseTexture = new THREE.CanvasTexture(noiseCanvas);
    noiseTexture.wrapS = THREE.RepeatWrapping;
    noiseTexture.wrapT = THREE.RepeatWrapping;
    noiseTexture.repeat.set(18, 18);

    const ground = new THREE.Mesh(groundGeo, new THREE.MeshStandardMaterial({
      vertexColors: true,
      roughness: 1.0,
      metalness: 0,
      flatShading: true,
      bumpMap: noiseTexture,
      bumpScale: 0.6,
    }));
    ground.rotation.x = -Math.PI / 2;
    scene.add(ground);

    const updateTerrain = (t: number) => {
      for (let i = 0; i < groundPositions.count; i++) {
        const { x, y } = vertexData[i];
        const dist = Math.sqrt(x * x + y * y);
        const edgeFade = Math.max(0, 1 - Math.pow(dist / (PLATFORM_SIZE * 1.1), 3));
        const dropOff = dist > PLATFORM_SIZE ? -(dist - PLATFORM_SIZE) * 0.5 : 0;
        groundPositions.setZ(i, getHeight(x, y, t) * edgeFade + dropOff);
      }
      groundPositions.needsUpdate = true;
      groundGeo.computeVertexNormals();
    };

    // Floating dust particles - sparse
    const dustCount = 30;
    const dustGeo = new THREE.BufferGeometry();
    const dustPositions = new Float32Array(dustCount * 3);
    const dustSizes = new Float32Array(dustCount);

    for (let i = 0; i < dustCount; i++) {
      const angle = Math.random() * Math.PI * 2;
      const dist = Math.random() * PLATFORM_SIZE * 1.2;
      dustPositions[i * 3] = Math.cos(angle) * dist;
      dustPositions[i * 3 + 1] = Math.random() * 40;
      dustPositions[i * 3 + 2] = Math.sin(angle) * dist;
      dustSizes[i] = Math.random() * 1.5 + 0.5;
    }

    dustGeo.setAttribute('position', new THREE.BufferAttribute(dustPositions, 3));
    dustGeo.setAttribute('size', new THREE.BufferAttribute(dustSizes, 1));

    const dustMat = new THREE.PointsMaterial({
      color: 0x6a5040,
      size: 0.8,
      transparent: true,
      opacity: 0.2,
      blending: THREE.AdditiveBlending,
      sizeAttenuation: true,
    });

    const dust = new THREE.Points(dustGeo, dustMat);
    scene.add(dust);

    // Dust clouds
    const createDustCloud = () => {
      const canvas = document.createElement('canvas');
      canvas.width = 256;
      canvas.height = 256;
      const ctx = canvas.getContext('2d')!;
      ctx.clearRect(0, 0, 256, 256);

      for (let i = 0; i < 30; i++) {
        const x = Math.random() * 256;
        const y = Math.random() * 256;
        const r = Math.random() * 60 + 30;
        const grad = ctx.createRadialGradient(x, y, 0, x, y, r);
        grad.addColorStop(0, 'rgba(40, 32, 25, 0.03)');
        grad.addColorStop(1, 'rgba(40, 32, 25, 0)');
        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, 256, 256);
      }

      return new THREE.CanvasTexture(canvas);
    };

    const dustClouds: THREE.Mesh[] = [];
    for (let i = 0; i < 2; i++) {
      const cloudGeo = new THREE.PlaneGeometry(200, 100);
      const cloudMat = new THREE.MeshBasicMaterial({
        map: createDustCloud(),
        transparent: true,
        opacity: 0.08,
        depthWrite: false,
        side: THREE.DoubleSide,
      });
      const cloud = new THREE.Mesh(cloudGeo, cloudMat);
      cloud.position.set(
        (Math.random() - 0.5) * 100,
        Math.random() * 30 + 5,
        (Math.random() - 0.5) * 100 - 30
      );
      cloud.rotation.y = Math.random() * Math.PI;
      dustClouds.push(cloud);
      scene.add(cloud);
    }

    // Physics
    const GRAVITY = 0.006;
    const FALL_GRAVITY = 0.02;
    const FRICTION = 0.992;
    const BOUNCE = 0.6;

    const boulders: THREE.Mesh[] = [];
    // Dark warm boulder colors - earthy with subtle bronze
    const boulderColors = [0x2a2420, 0x252018, 0x201a14, 0x2d2822, 0x231e18];

    const createBoulder = (radius: number, worldX: number, worldZ: number, dirX: number, dirZ: number, spd: number) => {
      // Higher subdivision for smoother, gap-free mesh
      const geo = new THREE.IcosahedronGeometry(radius, 3);
      const positions = geo.attributes.position;

      // Random seed for this boulder's lumpiness
      const seed = Math.random() * 1000;

      // Gentler shape distortion - store for physics
      const squashX = 0.9 + Math.random() * 0.2;
      const squashY = 0.9 + Math.random() * 0.2;
      const squashZ = 0.9 + Math.random() * 0.2;

      for (let i = 0; i < positions.count; i++) {
        const x = positions.getX(i);
        const y = positions.getY(i);
        const z = positions.getZ(i);

        // Get direction from center
        const len = Math.sqrt(x * x + y * y + z * z);
        const nx = x / len;
        const ny = y / len;
        const nz = z / len;

        // Big lumps
        const lump1 = Math.sin(nx * 2.5 + seed) * Math.cos(ny * 3 + seed) * Math.sin(nz * 2.8 + seed);
        // Medium lumps
        const lump2 = Math.sin(nx * 5 + seed * 2) * Math.cos(ny * 4.5 + seed * 2) * Math.sin(nz * 5.5 + seed * 2) * 0.6;
        // Small bumps
        const lump3 = Math.sin(nx * 9 + seed * 3) * Math.sin(nz * 8 + seed * 3) * 0.3;

        const displacement = (lump1 + lump2 + lump3) * radius * 0.25;

        positions.setX(i, x * squashX + nx * displacement);
        positions.setY(i, y * squashY + ny * displacement);
        positions.setZ(i, z * squashZ + nz * displacement);
      }

      geo.computeVertexNormals();

      const mat = new THREE.MeshStandardMaterial({
        color: boulderColors[Math.floor(Math.random() * boulderColors.length)],
        vertexColors: true,
        roughness: 0.82,
        metalness: 0.08,
        emissive: 0x120b04,
        emissiveIntensity: 0.12,
        flatShading: true,
      });

      const base = new THREE.Color(mat.color);
      const lightFacet = new THREE.Color(0x6b5540);
      const shadowFacet = new THREE.Color(0x100c09);
      const facetColors = new Float32Array(positions.count * 3);

      for (let i = 0; i < positions.count; i++) {
        const normalY = positions.getY(i) / radius;
        const warmth = Math.max(0, Math.min(1, normalY * 0.5 + 0.5));
        const color = base.clone()
          .lerp(shadowFacet, 0.22 * (1 - warmth))
          .lerp(lightFacet, 0.18 * warmth);

        facetColors[i * 3] = color.r;
        facetColors[i * 3 + 1] = color.g;
        facetColors[i * 3 + 2] = color.b;
      }

      geo.setAttribute('color', new THREE.BufferAttribute(facetColors, 3));
      const mesh = new THREE.Mesh(geo, mat);

      const h = getWorldHeight(worldX, worldZ, 0);
      mesh.position.set(worldX, h + radius, worldZ);

      mesh.userData = {
        radius,
        baseRadius: radius,
        squashX,
        squashY,
        squashZ,
        seed,
        velocity: new THREE.Vector3(dirX, 0, dirZ).normalize().multiplyScalar(spd),
        onGround: true,
        falling: false,
        mass: radius * radius * radius,
      };

      scene.add(mesh);
      boulders.push(mesh);
      return mesh;
    };

    createBoulder(5, 0, 15, 0.5, -0.5, 0.06);
    createBoulder(6, -25, 8, 0.6, -0.8, 0.05);
    createBoulder(4, 30, -10, -0.7, -0.3, 0.07);
    createBoulder(7, -15, -30, 0.4, 0.9, 0.04);
    createBoulder(4.5, 25, 30, -0.5, -0.6, 0.06);
    createBoulder(5.5, -35, 20, 0.8, -0.4, 0.05);
    createBoulder(4, 10, -25, -0.3, 0.7, 0.065);
    createBoulder(6.5, -10, 35, 0.6, -0.5, 0.045);
    createBoulder(5, 40, 5, -0.9, -0.2, 0.055);
    createBoulder(4.5, -40, -15, 0.7, 0.6, 0.05);

    const respawnBoulder = (b: THREE.Mesh, t: number) => {
      const angle = Math.random() * Math.PI * 2;
      const dist = 15 + Math.random() * 30;
      const wx = Math.cos(angle) * dist;
      const wz = Math.sin(angle) * dist;
      const h = getWorldHeight(wx, wz, t);

      b.position.set(wx, h + b.userData.baseRadius + 15, wz);

      const da = Math.random() * Math.PI * 2;
      b.userData.velocity.set(Math.cos(da) * 0.04, 0, Math.sin(da) * 0.04);
      b.userData.falling = false;
      b.userData.onGround = false;
    };

    const handleCollisions = () => {
      for (let i = 0; i < boulders.length; i++) {
        for (let j = i + 1; j < boulders.length; j++) {
          const a = boulders[i];
          const b = boulders[j];

          if (a.userData.falling || b.userData.falling) continue;

          const diff = new THREE.Vector3().subVectors(b.position, a.position);
          const dist = diff.length();
          const minDist = a.userData.baseRadius + b.userData.baseRadius;

          if (dist < minDist && dist > 0.01) {
            const normal = diff.clone().normalize();

            const overlap = minDist - dist;
            const totalMass = a.userData.mass + b.userData.mass;
            a.position.sub(normal.clone().multiplyScalar(overlap * 0.5 * b.userData.mass / totalMass));
            b.position.add(normal.clone().multiplyScalar(overlap * 0.5 * a.userData.mass / totalMass));

            const relVel = new THREE.Vector3().subVectors(a.userData.velocity, b.userData.velocity);
            const velAlongNormal = relVel.dot(normal);

            if (velAlongNormal > 0) {
              const impulse = (-(1 + BOUNCE) * velAlongNormal) / (1/a.userData.mass + 1/b.userData.mass);
              const impulseVec = normal.clone().multiplyScalar(impulse);
              a.userData.velocity.add(impulseVec.clone().multiplyScalar(1/a.userData.mass));
              b.userData.velocity.sub(impulseVec.clone().multiplyScalar(1/b.userData.mass));
            }
          }
        }
      }
    };

    let mouseX = 0, mouseY = 0;
    const onMouseMove = (e: MouseEvent) => {
      mouseX = (e.clientX / window.innerWidth - 0.5) * 2;
      mouseY = (e.clientY / window.innerHeight - 0.5) * 2;
    };
    window.addEventListener('mousemove', onMouseMove);

    const animate = () => {
      if (disposed) return;
      animationFrameId = requestAnimationFrame(animate);

      time += 0.006;
      updateTerrain(time);

      camera.position.x += (mouseX * 25 - camera.position.x) * 0.02;
      camera.position.y += (20 - mouseY * 10 - camera.position.y) * 0.02;
      camera.lookAt(0, 0, -10);

      // Animate dust
      const dustPos = dust.geometry.attributes.position.array as Float32Array;
      for (let i = 0; i < dustCount; i++) {
        dustPos[i * 3] += Math.sin(time * 0.5 + i) * 0.02;
        dustPos[i * 3 + 1] += Math.sin(time * 0.3 + i * 0.5) * 0.015;
        dustPos[i * 3 + 2] += Math.cos(time * 0.4 + i * 0.3) * 0.02;
      }
      dust.geometry.attributes.position.needsUpdate = true;

      // Animate dust clouds
      dustClouds.forEach((cloud, i) => {
        cloud.position.x += Math.sin(time * 0.2 + i) * 0.05;
        cloud.position.z += 0.02;
        if (cloud.position.z > 80) cloud.position.z = -80;
      });

      handleCollisions();

      boulders.forEach((b) => {
        const { baseRadius, velocity, squashX, squashY, squashZ, seed } = b.userData;
        const wx = b.position.x;
        const wz = b.position.z;

        // Calculate effective radius based on current rotation
        // Get the "down" vector in local space
        const downWorld = new THREE.Vector3(0, -1, 0);
        const invQuat = b.quaternion.clone().invert();
        const downLocal = downWorld.applyQuaternion(invQuat);

        // Effective radius is the squash in the "down" direction
        // Plus some lump variation based on angle
        const lumpPhase = Math.atan2(downLocal.z, downLocal.x) + seed;
        const lumpVar = Math.sin(lumpPhase * 3) * 0.08 + Math.sin(lumpPhase * 7) * 0.04;

        const effectiveRadius = baseRadius * (
          Math.abs(downLocal.x) * squashX +
          Math.abs(downLocal.y) * squashY +
          Math.abs(downLocal.z) * squashZ +
          lumpVar
        );

        const distFromCenter = Math.sqrt(wx * wx + wz * wz);

        if (distFromCenter > PLATFORM_SIZE && !b.userData.falling) {
          b.userData.falling = true;
          b.userData.onGround = false;
        }

        if (b.userData.falling) {
          velocity.y -= FALL_GRAVITY;
          b.position.add(velocity);
          b.rotation.x += 0.03;
          b.rotation.z += 0.02;

          if (b.position.y < -100) {
            respawnBoulder(b, time);
          }
        } else {
          const grad = getWorldGradient(wx, wz, time);
          velocity.x -= grad.x * GRAVITY;
          velocity.z -= grad.z * GRAVITY;
          velocity.multiplyScalar(FRICTION);

          b.position.x += velocity.x;
          b.position.z += velocity.z;

          const speed = Math.sqrt(velocity.x * velocity.x + velocity.z * velocity.z);
          if (speed > 0.001) {
            const dir = new THREE.Vector3(velocity.x, 0, velocity.z).normalize();
            const axis = new THREE.Vector3(dir.z, 0, -dir.x);
            // Angular velocity varies with effective radius - wobble!
            const angularSpeed = speed / effectiveRadius;
            b.rotateOnWorldAxis(axis, angularSpeed);
          }

          // Height follows terrain + effective radius (causes bobbing)
          const h = getWorldHeight(b.position.x, b.position.z, time);
          const targetY = h + effectiveRadius;

          if (!b.userData.onGround) {
            velocity.y -= GRAVITY * 2;
            b.position.y += velocity.y;
            if (b.position.y <= targetY) {
              b.position.y = targetY;
              velocity.y = 0;
              b.userData.onGround = true;
            }
          } else {
            b.position.y = targetY;
          }
        }
      });

      // Update twinkling stars and render sky
      updateTwinkle(time * 3);
      renderer.setRenderTarget(skyRenderTarget);
      renderer.render(skyScene, skyCamera);
      renderer.setRenderTarget(null);

      renderer.render(scene, camera);
      animateGrain(mouseX, mouseY, time, boulders, camera);
    };

    animate();

    const handleResize = () => {
      if (!containerRef.current) return;
      camera.aspect = containerRef.current.clientWidth / containerRef.current.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setPixelRatio(getPixelRatio());
      renderer.setSize(containerRef.current.clientWidth, containerRef.current.clientHeight);
      updateGrain();
    };
    window.addEventListener('resize', handleResize);

    return () => {
      disposed = true;
      cancelAnimationFrame(animationFrameId);
      window.removeEventListener('resize', handleResize);
      window.removeEventListener('mousemove', onMouseMove);
      renderer.domElement.removeEventListener('webglcontextlost', handleContextLost);
      if (grainCanvas.parentNode) grainCanvas.parentNode.removeChild(grainCanvas);
      if (glowCanvas.parentNode) glowCanvas.parentNode.removeChild(glowCanvas);
      if (renderer.domElement.parentNode) renderer.domElement.parentNode.removeChild(renderer.domElement);
      boulders.forEach((b) => {
        b.geometry.dispose();
        if (Array.isArray(b.material)) {
          b.material.forEach((material) => material.dispose());
        } else {
          b.material.dispose();
        }
      });
      groundGeo.dispose();
      noiseTexture.dispose();
      dustGeo.dispose();
      dustMat.dispose();
      dustClouds.forEach((cloud) => {
        cloud.geometry.dispose();
        if (Array.isArray(cloud.material)) {
          cloud.material.forEach((material) => material.dispose());
        } else {
          (cloud.material as THREE.MeshBasicMaterial).map?.dispose();
          cloud.material.dispose();
        }
      });
      bgTexture.dispose();
      twinkleTexture.dispose();
      skyGeo.dispose();
      skyMat.dispose();
      skyRenderTarget.dispose();
      renderer.dispose();
      sceneRef.current = false;
    };
  }, []);

  return (
    <div
      ref={containerRef}
      className="w-full h-screen"
      style={{
        position: 'relative',
        overflow: 'hidden',
        background:
          'radial-gradient(circle at 50% 35%, rgba(42, 30, 18, 0.28), rgba(1, 1, 1, 0.96) 62%, #010101 100%)',
      }}
    />
  );
}
