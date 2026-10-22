/* =========================================================================
   FindMeGamer — hero scene

   Everything here is drawn in code: the studio environment is a hand-built
   PMREM scene (softboxes, a warm paper bounce), the ring is a clearcoat torus
   and the satellites are lit only by that environment.

   Ornament, not product: it is the idea of a selective orbit, not a screenshot
   and not live data. If WebGL is missing, slow, or the visitor asked for less
   motion, main.js never loads this and the static illustration stays.

   Loaded lazily by main.js.
   ========================================================================= */
import * as THREE from "../vendor/three.module.min.js";

const PAPER = 0xf7f3ea;

const SATELLITES = [
  { orbit: 0, angle: 0.42, size: 0.145, tone: "mint", link: true },
  { orbit: 1, angle: 2.42, size: 0.19, tone: "cobalt", link: true },
  { orbit: 1, angle: 4.1, size: 0.105, tone: "cream" },
  { orbit: 0, angle: 4.86, size: 0.125, tone: "mint", link: true },
  { orbit: 1, angle: 5.74, size: 0.085, tone: "mint" },
];

const ORBITS = [
  { rx: 2.36, tilt: [-0.94, 0.12, 0.34], opacity: 0.42 },
  { rx: 2.8, tilt: [-1.18, -0.18, -0.1], opacity: 0.26 },
];

/* A small studio built from planes: this is what the glass reflects. Bright
   values above 1 stay in the half-float environment target, so highlights on
   the clearcoat read as real light rather than as white paint. */
function buildStudio(renderer) {
  const pmrem = new THREE.PMREMGenerator(renderer);
  const studio = new THREE.Scene();

  // A dim room with one wide, warm opening above and a cool rim behind: matte
  // surfaces turn that gradient into the object's form.
  studio.add(
    new THREE.Mesh(
      new THREE.BoxGeometry(26, 26, 26),
      new THREE.MeshBasicMaterial({
        color: new THREE.Color(0.14, 0.13, 0.115),
        side: THREE.BackSide,
      })
    )
  );

  function panel(intensity, tint, position, size, lookAt = [0, 0, 0]) {
    const mesh = new THREE.Mesh(
      new THREE.PlaneGeometry(size[0], size[1]),
      new THREE.MeshBasicMaterial({ color: tint, side: THREE.DoubleSide })
    );
    mesh.material.color.multiplyScalar(intensity);
    mesh.position.set(...position);
    mesh.lookAt(new THREE.Vector3(...lookAt));
    studio.add(mesh);
    return mesh;
  }

  // Wide warm sky.
  panel(2.1, new THREE.Color(1, 0.975, 0.93), [-2, 11, 5], [18, 18]);
  // Cool side wall, for the shadow side of every form.
  panel(0.55, new THREE.Color(0.78, 0.86, 1), [9, 1, 2], [14, 14]);
  // A strip that draws one clean highlight down the ring.
  panel(3.2, new THREE.Color(1, 1, 1), [-7, 5, 3], [1.1, 12]);
  // Warm bounce from the page.
  panel(0.5, new THREE.Color(1, 0.93, 0.79), [0, -9, 3], [18, 18]);

  const target = pmrem.fromScene(studio, 0.02);
  pmrem.dispose();
  studio.traverse((child) => {
    if (child.geometry) child.geometry.dispose();
    if (child.material) child.material.dispose();
  });
  return target;
}

export function init(stage, options = {}) {
  const lite = options.lite === true;
  const canvas = stage.querySelector(".stage__canvas");
  if (!canvas) throw new Error("No canvas in stage");

  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: !lite,
    alpha: false,
    powerPreference: "high-performance",
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, lite ? 1.5 : 2));
  renderer.setClearColor(PAPER, 1);
  renderer.toneMapping = THREE.NeutralToneMapping;
  renderer.toneMappingExposure = 1.02;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(PAPER);

  const environment = buildStudio(renderer);
  scene.environment = environment.texture;
  scene.environmentIntensity = 0.8;

  const camera = new THREE.PerspectiveCamera(26, 1, 0.1, 100);
  camera.position.set(0, 1.2, 8.8);
  camera.lookAt(0, -0.05, 0);

  /* ------------------------------------------------------------- lighting */
  const rim = new THREE.DirectionalLight(0xbcd0ff, 1.7);
  rim.position.set(1.2, 3.4, -6.2);
  scene.add(rim);

  const fill = new THREE.DirectionalLight(0xdff0e4, 0.5);
  fill.position.set(6, -1, 3);
  scene.add(fill);

  const key = new THREE.DirectionalLight(0xfff3e0, 2.4);
  key.position.set(-3.1, 6.6, 3.2);
  key.castShadow = true;
  key.shadow.mapSize.set(lite ? 512 : 2048, lite ? 512 : 2048);
  key.shadow.camera.left = -3.4;
  key.shadow.camera.right = 3.4;
  key.shadow.camera.top = 3.4;
  key.shadow.camera.bottom = -3.4;
  key.shadow.camera.near = 1;
  key.shadow.camera.far = 18;
  key.shadow.bias = -0.0006;
  key.shadow.normalBias = 0.015;
  key.shadow.radius = 7;
  scene.add(key);

  /* -------------------------------------------------------------- staging */
  const pivot = new THREE.Group();
  scene.add(pivot);
  const world = new THREE.Group();
  world.position.x = 0.5;
  pivot.add(world);

  const shadowPlane = new THREE.Mesh(
    new THREE.PlaneGeometry(24, 24),
    new THREE.ShadowMaterial({ color: 0x2d2b24, opacity: 0.15 })
  );
  shadowPlane.rotation.x = -Math.PI / 2;
  shadowPlane.position.y = -1.12;
  shadowPlane.receiveShadow = true;
  scene.add(shadowPlane);

  function contactTexture() {
    const size = 256;
    const surface = document.createElement("canvas");
    surface.width = size;
    surface.height = size;
    const context = surface.getContext("2d");
    const gradient = context.createRadialGradient(
      size / 2,
      size / 2,
      0,
      size / 2,
      size / 2,
      size / 2
    );
    gradient.addColorStop(0, "rgba(38,34,26,0.55)");
    gradient.addColorStop(0.42, "rgba(44,40,32,0.24)");
    gradient.addColorStop(1, "rgba(44,40,32,0)");
    context.fillStyle = gradient;
    context.fillRect(0, 0, size, size);
    const texture = new THREE.CanvasTexture(surface);
    texture.colorSpace = THREE.SRGBColorSpace;
    return texture;
  }

  // A quiet pool of shading directly beneath the object: the light does the
  // rest, but this is what stops it floating above the paper.
  const contact = new THREE.Mesh(
    new THREE.PlaneGeometry(5.4, 5.4),
    new THREE.MeshBasicMaterial({
      map: contactTexture(),
      transparent: true,
      depthWrite: false,
      opacity: 0.55,
    })
  );
  contact.rotation.x = -Math.PI / 2;
  contact.position.set(0.42, -1.1, 0.08);
  contact.visible = false;

  /* ------------------------------------------------------------ materials */
  // Polished cobalt — an enamel object rather than glass: on a flat paper
  // background a transmissive material has nothing to refract and reads as
  // coloured plastic, while clearcoat highlights carry the form instead.
  const enamel = new THREE.MeshPhysicalMaterial({
    color: 0x1834e4,
    roughness: 0.17,
    metalness: 0,
    clearcoat: 1,
    clearcoatRoughness: 0.05,
    envMapIntensity: 1.15,
    iridescence: 0.1,
    iridescenceIOR: 1.4,
    iridescenceThicknessRange: [160, 420],
  });

  const cream = new THREE.MeshPhysicalMaterial({
    color: 0xf3e8d2,
    roughness: 0.48,
    metalness: 0,
    clearcoat: 0.5,
    clearcoatRoughness: 0.35,
    envMapIntensity: 0.85,
  });

  const mint = new THREE.MeshPhysicalMaterial({
    color: 0xa6d8b9,
    roughness: 0.34,
    metalness: 0,
    clearcoat: 0.7,
    clearcoatRoughness: 0.2,
    envMapIntensity: 0.95,
  });

  const cobalt = new THREE.MeshPhysicalMaterial({
    color: 0x162cd4,
    roughness: 0.14,
    metalness: 0,
    clearcoat: 1,
    clearcoatRoughness: 0.05,
    envMapIntensity: 1.1,
  });

  /* ----------------------------------------------------------------- ring */
  const ringFrame = new THREE.Group();
  ringFrame.rotation.set(-1.32, 0.2, 0.1);
  world.add(ringFrame);

  const hoop = new THREE.Mesh(
    new THREE.TorusGeometry(1.02, 0.285, lite ? 18 : 32, lite ? 64 : 190),
    enamel
  );
  hoop.castShadow = true;
  ringFrame.add(hoop);

  // The one that fits: a cream ball resting in the opening of the hoop.
  const keeper = new THREE.Mesh(
    new THREE.SphereGeometry(0.5, lite ? 20 : 46, lite ? 14 : 32),
    cream
  );
  keeper.position.set(0.02, -0.06, 0.06);
  keeper.castShadow = true;
  ringFrame.add(keeper);

  /* ---------------------------------------------------------------- props */
  // One companion form at the edge of the hoop, for depth and asymmetry.
  const companion = new THREE.Mesh(
    new THREE.SphereGeometry(0.2, lite ? 16 : 32, lite ? 12 : 24),
    mint
  );
  companion.position.set(-1.16, -0.36, 0.62);
  companion.castShadow = true;
  world.add(companion);

  /* --------------------------------------------------------------- orbits */
  const orbitGroups = ORBITS.map((orbit) => {
    const group = new THREE.Group();
    group.rotation.set(orbit.tilt[0], orbit.tilt[1], orbit.tilt[2]);
    world.add(group);

    const points = [];
    for (let i = 0; i <= 200; i += 1) {
      const angle = (i / 200) * Math.PI * 2;
      points.push(
        new THREE.Vector3(Math.cos(angle) * orbit.rx, Math.sin(angle) * orbit.rx, 0)
      );
    }
    group.add(
      new THREE.LineLoop(
        new THREE.BufferGeometry().setFromPoints(points),
        new THREE.LineBasicMaterial({
          color: 0xb3a894,
          transparent: true,
          opacity: orbit.opacity,
          depthWrite: false,
        })
      )
    );
    return group;
  });

  /* ----------------------------------------------------------- satellites */
  const sphere = new THREE.SphereGeometry(1, lite ? 16 : 36, lite ? 12 : 26);
  const nodes = [];

  world.updateMatrixWorld(true);

  SATELLITES.forEach((spec) => {
    const orbit = orbitGroups[spec.orbit];
    const position = new THREE.Vector3(
      Math.cos(spec.angle) * ORBITS[spec.orbit].rx,
      Math.sin(spec.angle) * ORBITS[spec.orbit].rx,
      0
    ).applyMatrix4(orbit.matrix);

    const mesh = new THREE.Mesh(
      sphere,
      spec.tone === "mint" ? mint : spec.tone === "cream" ? cream : cobalt
    );
    mesh.scale.setScalar(spec.size);
    mesh.position.copy(position);
    mesh.castShadow = true;
    world.add(mesh);
    nodes.push({ mesh, spec, position });
  });

  /* ------------------------------------------------------------ filaments */
  const filaments = [];
  const beadGeometry = new THREE.SphereGeometry(1, 12, 10);

  nodes
    .filter((node) => node.spec.link)
    .forEach((node, index) => {
      const anchorAngle = 1.1 + index * 2.05;
      const anchor = new THREE.Vector3(
        Math.cos(anchorAngle) * 1.13,
        Math.sin(anchorAngle) * 1.13,
        0
      ).applyMatrix4(ringFrame.matrix);

      const curve = new THREE.QuadraticBezierCurve3(
        anchor.clone(),
        anchor.clone().lerp(node.position, 0.5).multiplyScalar(1.24),
        node.position.clone()
      );

      world.add(
        new THREE.Mesh(
          new THREE.TubeGeometry(curve, lite ? 24 : 64, 0.0068, 5, false),
          new THREE.MeshBasicMaterial({
            color: 0x2440ff,
            transparent: true,
            opacity: 0.32,
            depthWrite: false,
          })
        )
      );

      const bead = new THREE.Mesh(
        beadGeometry,
        new THREE.MeshBasicMaterial({
          color: 0xf4fffa,
          transparent: true,
          opacity: 0.92,
          depthWrite: false,
        })
      );
      world.add(bead);

      filaments.push({
        curve,
        bead,
        phase: index * 0.36,
        speed: 0.15 + index * 0.03,
      });
    });

  /* ----------------------------------------------------------------- frame */
  const fitWidth = 4.05;
  const fitHeight = 3.85;

  function resize() {
    const width = stage.clientWidth || 1;
    const height = stage.clientHeight || 1;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;

    const vFov = (camera.fov * Math.PI) / 180;
    const visibleHeight = 2 * Math.tan(vFov / 2) * camera.position.length();
    const visibleWidth = visibleHeight * camera.aspect;
    const scale = Math.min(
      1.55,
      (visibleWidth * 0.98) / fitWidth,
      (visibleHeight * 0.95) / fitHeight
    );
    world.scale.setScalar(scale);
    camera.updateProjectionMatrix();
  }
  resize();

  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(stage);

  /* ----------------------------------------------------------- interaction */
  let running = true;
  let visible = true;
  const clock = new THREE.Clock();
  let elapsed = 0;

  const state = {
    dragging: false,
    pointerId: null,
    lastX: 0,
    lastY: 0,
    spin: -0.2,
    tilt: 0.02,
    spinVelocity: 0,
    tiltVelocity: 0,
  };

  world.rotation.y = state.spin;
  pivot.rotation.x = state.tilt;

  const pointer = { x: 0, y: 0 };
  const parallax = { x: 0, y: 0 };

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function onPointerDown(event) {
    if (event.button !== undefined && event.button !== 0) return;
    state.dragging = true;
    state.pointerId = event.pointerId;
    state.lastX = event.clientX;
    state.lastY = event.clientY;
    state.spinVelocity = 0;
    state.tiltVelocity = 0;
    stage.classList.add("is-dragging");
    if (canvas.setPointerCapture) {
      try {
        canvas.setPointerCapture(event.pointerId);
      } catch (error) {
        /* ignore */
      }
    }
  }

  function onPointerMove(event) {
    const rect = stage.getBoundingClientRect();
    pointer.x = ((event.clientX - rect.left) / rect.width - 0.5) * 2;
    pointer.y = ((event.clientY - rect.top) / rect.height - 0.5) * 2;

    if (!state.dragging || event.pointerId !== state.pointerId) return;
    const dx = event.clientX - state.lastX;
    const dy = event.clientY - state.lastY;
    state.lastX = event.clientX;
    state.lastY = event.clientY;
    state.spin += dx * 0.0062;
    state.tilt = clamp(state.tilt + dy * 0.0034, -0.3, 0.3);
    state.spinVelocity = dx * 0.0062 * 16;
    state.tiltVelocity = dy * 0.0034 * 16;
  }

  function onPointerUp(event) {
    if (event.pointerId !== state.pointerId) return;
    state.dragging = false;
    state.pointerId = null;
    stage.classList.remove("is-dragging");
  }

  canvas.addEventListener("pointerdown", onPointerDown);
  canvas.addEventListener("pointermove", onPointerMove);
  canvas.addEventListener("pointerup", onPointerUp);
  canvas.addEventListener("pointercancel", onPointerUp);
  canvas.addEventListener("pointerleave", function () {
    pointer.x = 0;
    pointer.y = 0;
  });

  /* ------------------------------------------------------------- lifecycle */
  function onContextLost(event) {
    event.preventDefault();
    running = false;
    stage.classList.remove("is-live", "is-draggable", "is-dragging");
  }
  canvas.addEventListener("webglcontextlost", onContextLost, false);

  const visibility = new IntersectionObserver(
    (entries) => {
      visible = entries.some((entry) => entry.isIntersecting);
      if (visible && running) clock.getDelta();
    },
    { threshold: 0 }
  );
  visibility.observe(stage);

  function onDocumentHidden() {
    if (document.hidden) clock.getDelta();
  }
  document.addEventListener("visibilitychange", onDocumentHidden);

  /* ------------------------------------------------------------------- loop */
  const beadPoint = new THREE.Vector3();
  let frameHandle = null;

  function render() {
    const delta = Math.min(clock.getDelta(), 0.05);
    elapsed += delta;

    if (!state.dragging) {
      const damping = Math.pow(0.02, delta);
      state.spin += state.spinVelocity * delta;
      state.tilt = clamp(state.tilt + state.tiltVelocity * delta, -0.3, 0.3);
      state.spinVelocity *= damping;
      state.tiltVelocity *= damping;
    }

    world.rotation.y = state.spin + elapsed * 0.055;
    pivot.rotation.x = state.tilt;

    parallax.x += (pointer.x * 0.24 - parallax.x) * 0.045;
    parallax.y += (-pointer.y * 0.14 - parallax.y) * 0.045;
    camera.position.x = parallax.x;
    camera.position.y = 1.2 + parallax.y;
    camera.lookAt(0, -0.05, 0);

    world.position.y = Math.sin(elapsed * 0.45) * 0.028;

    filaments.forEach((filament) => {
      const travel = (elapsed * filament.speed + filament.phase) % 1;
      const eased =
        travel < 0.08 ? travel / 0.08 : travel > 0.92 ? (1 - travel) / 0.08 : 1;
      filament.curve.getPointAt(clamp(travel, 0.001, 0.999), beadPoint);
      filament.bead.position.copy(beadPoint);
      filament.bead.scale.setScalar(
        0.03 * Math.max(0.001, eased) * (0.72 + 0.28 * Math.sin(travel * Math.PI))
      );
    });

    renderer.render(scene, camera);
  }

  function frame() {
    if (!running) return;
    frameHandle = requestAnimationFrame(frame);
    if (!visible || document.hidden) return;
    render();
  }

  render();
  frameHandle = requestAnimationFrame(frame);

  return {
    dispose() {
      running = false;
      if (frameHandle) cancelAnimationFrame(frameHandle);
      visibility.disconnect();
      resizeObserver.disconnect();
      document.removeEventListener("visibilitychange", onDocumentHidden);
      canvas.removeEventListener("webglcontextlost", onContextLost);
      canvas.removeEventListener("pointerdown", onPointerDown);
      canvas.removeEventListener("pointermove", onPointerMove);
      canvas.removeEventListener("pointerup", onPointerUp);
      canvas.removeEventListener("pointercancel", onPointerUp);
      scene.traverse((child) => {
        if (child.geometry) child.geometry.dispose();
        if (child.material) {
          if (Array.isArray(child.material)) {
            child.material.forEach((material) => material.dispose());
          } else {
            child.material.dispose();
          }
        }
      });
      environment.dispose();
      renderer.dispose();
    },
  };
}
