/* =========================================================================
   FindMeGamer — live signal field

   A slow field of candidate nodes behind the "How it works" band, where only a
   handful are connected and a signal travels along each connection. It is
   ornament for the idea of the product — selective matches, not a dashboard and
   not live data.

   Purely decorative: pointer-events are off, nothing here is focusable, and the
   section reads completely without it. Loaded lazily by main.js; the static
   orbit line-art behind the copy stays if this never runs.
   ========================================================================= */
import * as THREE from "../vendor/three.module.min.js";

const COBALT = 0x3a55ff;
const MINT = 0x9ad3b0;
const PAPER = 0xe8e2d4;

const NODE_COUNT = 74;
const LINKS = 7;

function seeded(seed) {
  let value = seed;
  return function random() {
    value = (value * 16807) % 2147483647;
    return (value - 1) / 2147483646;
  };
}

export function init(stage, options = {}) {
  const lite = options.lite === true;
  const canvas = stage.querySelector(".field__canvas");
  if (!canvas) throw new Error("No canvas in field");

  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: false,
    alpha: true,
    powerPreference: "low-power",
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, lite ? 1.2 : 1.75));
  renderer.setClearColor(0x000000, 0);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(46, 1, 0.1, 100);
  camera.position.set(0, 0, 9);

  const world = new THREE.Group();
  scene.add(world);

  /* ----------------------------------------------------------------- nodes */
  const random = seeded(20261022);
  const bases = [];
  const tones = [];

  for (let i = 0; i < NODE_COUNT; i += 1) {
    const radius = 3.2 + random() * 6.4;
    const angle = random() * Math.PI * 2;
    const height = (random() - 0.5) * 5.4;
    bases.push(
      new THREE.Vector3(
        Math.cos(angle) * radius * 0.85,
        height,
        Math.sin(angle) * radius * 0.5
      )
    );
    tones.push(random());
  }

  // A soft round sprite: at this scale hard spheres read as dead pixels.
  function dotTexture() {
    const size = 64;
    const canvasEl = document.createElement("canvas");
    canvasEl.width = size;
    canvasEl.height = size;
    const context = canvasEl.getContext("2d");
    const gradient = context.createRadialGradient(
      size / 2,
      size / 2,
      0,
      size / 2,
      size / 2,
      size / 2
    );
    gradient.addColorStop(0, "rgba(255,255,255,1)");
    gradient.addColorStop(0.45, "rgba(255,255,255,0.72)");
    gradient.addColorStop(1, "rgba(255,255,255,0)");
    context.fillStyle = gradient;
    context.beginPath();
    context.arc(size / 2, size / 2, size / 2, 0, Math.PI * 2);
    context.fill();
    const texture = new THREE.Texture(canvasEl);
    texture.needsUpdate = true;
    return texture;
  }

  const sprite = dotTexture();
  const buckets = [
    { size: 0.13, opacity: 0.42, list: [] },
    { size: 0.2, opacity: 0.6, list: [] },
    { size: 0.32, opacity: 0.85, list: [] },
  ];

  const colour = new THREE.Color();
  for (let i = 0; i < NODE_COUNT; i += 1) {
    const tone = tones[i];
    if (tone > 0.94) {
      colour.setHex(COBALT);
    } else if (tone > 0.78) {
      colour.setHex(MINT);
    } else {
      colour.setHex(PAPER);
    }
    const weight = tone > 0.94 ? 2 : tone > 0.78 ? 1 : 0;
    buckets[weight].list.push({ index: i, color: colour.clone() });
  }

  const nodeGroups = buckets.map((bucket) => {
    const count = bucket.list.length;
    const positions = new Float32Array(count * 3);
    const colors = new Float32Array(count * 3);
    bucket.list.forEach((entry, i) => {
      colors[i * 3] = entry.color.r;
      colors[i * 3 + 1] = entry.color.g;
      colors[i * 3 + 2] = entry.color.b;
    });
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    const points = new THREE.Points(
      geometry,
      new THREE.PointsMaterial({
        map: sprite,
        size: bucket.size,
        sizeAttenuation: true,
        transparent: true,
        opacity: bucket.opacity,
        depthWrite: false,
        vertexColors: true,
        blending: THREE.AdditiveBlending,
      })
    );
    world.add(points);
    return { geometry, positions, list: bucket.list };
  });

  /* ----------------------------------------------------------------- links */
  const linkSource = [];
  const linkTarget = [];
  for (let i = 0; i < LINKS; i += 1) {
    linkSource.push(Math.floor(random() * NODE_COUNT));
    linkTarget.push(Math.floor(random() * NODE_COUNT));
  }

  const SEGMENTS = 26;
  const links = linkSource.map((from, index) => {
    const positions = new Float32Array((SEGMENTS + 1) * 3);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    const line = new THREE.Line(
      geometry,
      new THREE.LineBasicMaterial({
        color: index % 3 === 0 ? COBALT : MINT,
        transparent: true,
        opacity: 0.3,
        depthWrite: false,
      })
    );
    world.add(line);

    const bead = new THREE.Mesh(
      new THREE.SphereGeometry(1, 8, 6),
      new THREE.MeshBasicMaterial({
        color: 0xdff6e7,
        transparent: true,
        opacity: 0.85,
        depthWrite: false,
      })
    );
    world.add(bead);

    return {
      from: linkSource[index],
      to: linkTarget[index],
      line,
      positions,
      bead,
      phase: random(),
      speed: 0.06 + random() * 0.06,
    };
  });

  /* ---------------------------------------------------------------- sizing */
  function resize() {
    const width = stage.clientWidth || 1;
    const height = stage.clientHeight || 1;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    const spread = Math.max(1.15, 1.9 - camera.aspect * 0.32);
    camera.position.z = 9 * spread;
    camera.updateProjectionMatrix();
  }
  resize();

  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(stage);

  /* ---------------------------------------------------------------- motion */
  let running = true;
  let visible = false;
  let elapsed = 0;
  const clock = new THREE.Clock();
  const point = new THREE.Vector3();
  const curve = new THREE.QuadraticBezierCurve3(
    new THREE.Vector3(),
    new THREE.Vector3(),
    new THREE.Vector3()
  );
  const start = new THREE.Vector3();
  const end = new THREE.Vector3();
  const control = new THREE.Vector3();

  function nodePosition(index, time, out) {
    const base = bases[index];
    const drift = Math.sin(time * 0.22 + index * 0.7) * 0.32;
    out.set(
      base.x + Math.cos(time * 0.16 + index) * 0.22,
      base.y + drift,
      base.z + Math.sin(time * 0.13 + index * 0.5) * 0.18
    );
    return out;
  }

  const visibility = new IntersectionObserver(
    (entries) => {
      visible = entries.some((entry) => entry.isIntersecting);
      if (visible) clock.getDelta();
    },
    { threshold: 0 }
  );
  visibility.observe(stage);

  function onDocumentHidden() {
    if (document.hidden) clock.getDelta();
  }
  document.addEventListener("visibilitychange", onDocumentHidden);

  function frame() {
    if (!running) return;
    requestAnimationFrame(frame);
    if (!visible || document.hidden) return;

    const delta = Math.min(clock.getDelta(), 0.05);
    elapsed += delta;

    world.rotation.y = elapsed * 0.028;
    world.rotation.x = Math.sin(elapsed * 0.05) * 0.05;

    nodeGroups.forEach((group) => {
      group.list.forEach((entry, i) => {
        nodePosition(entry.index, elapsed, point);
        group.positions[i * 3] = point.x;
        group.positions[i * 3 + 1] = point.y;
        group.positions[i * 3 + 2] = point.z;
      });
      group.geometry.attributes.position.needsUpdate = true;
    });

    links.forEach((link) => {
      nodePosition(link.from, elapsed, start);
      nodePosition(link.to, elapsed, end);

      control.copy(start).lerp(end, 0.5);
      control.y += 0.9;
      control.z += 0.4;

      curve.v0.copy(start);
      curve.v1.copy(control);
      curve.v2.copy(end);

      const points = curve.getPoints(SEGMENTS);
      for (let i = 0; i < points.length; i += 1) {
        link.positions[i * 3] = points[i].x;
        link.positions[i * 3 + 1] = points[i].y;
        link.positions[i * 3 + 2] = points[i].z;
      }
      link.line.geometry.attributes.position.needsUpdate = true;

      const travel = (elapsed * link.speed + link.phase) % 1;
      const eased =
        travel < 0.1 ? travel / 0.1 : travel > 0.9 ? (1 - travel) / 0.1 : 1;
      curve.getPointAt(Math.min(0.999, Math.max(0.001, travel)), point);
      link.bead.position.copy(point);
      link.bead.scale.setScalar(0.045 * Math.max(0.001, eased));
      link.line.material.opacity = 0.2 + 0.18 * Math.sin(travel * Math.PI);
    });

    renderer.render(scene, camera);
  }

  requestAnimationFrame(frame);

  return {
    dispose() {
      running = false;
      visibility.disconnect();
      resizeObserver.disconnect();
      document.removeEventListener("visibilitychange", onDocumentHidden);
      scene.traverse((child) => {
        if (child.geometry) child.geometry.dispose();
        if (child.material) child.material.dispose();
      });
      renderer.dispose();
    },
  };
}
