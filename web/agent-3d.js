(() => {
  const container = document.getElementById('ai-worker-canvas');
  if (!container || !window.THREE) return;

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0x07101c, 7, 15);

  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
  camera.position.set(0.2, 2.2, 7.6);
  camera.lookAt(0, 1.35, 0);

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  container.appendChild(renderer.domElement);

  const hemi = new THREE.HemisphereLight(0x8fdcff, 0x08111e, 2.1);
  scene.add(hemi);
  const key = new THREE.DirectionalLight(0xffffff, 3.2);
  key.position.set(4, 7, 5);
  key.castShadow = true;
  scene.add(key);
  const rim = new THREE.PointLight(0x4aa8ff, 18, 12);
  rim.position.set(-3, 3, 3);
  scene.add(rim);

  const floor = new THREE.Mesh(
    new THREE.CircleGeometry(4.8, 64),
    new THREE.MeshStandardMaterial({ color: 0x0a1624, metalness: 0.45, roughness: 0.72 })
  );
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  scene.add(floor);

  const grid = new THREE.GridHelper(9, 22, 0x2f7fc1, 0x15344f);
  grid.position.y = 0.006;
  scene.add(grid);

  const worker = new THREE.Group();
  scene.add(worker);

  const skin = new THREE.MeshStandardMaterial({ color: 0xb67c5b, roughness: 0.68 });
  const suit = new THREE.MeshStandardMaterial({ color: 0x1c3a66, metalness: 0.5, roughness: 0.34 });
  const dark = new THREE.MeshStandardMaterial({ color: 0x101722, metalness: 0.35, roughness: 0.5 });
  const glowBlue = new THREE.MeshStandardMaterial({ color: 0x4cc9ff, emissive: 0x1688cc, emissiveIntensity: 2.5 });
  const glowGreen = new THREE.MeshStandardMaterial({ color: 0x4ce08a, emissive: 0x1ca45e, emissiveIntensity: 2.1 });

  function mesh(geometry, material, position, rotation = [0, 0, 0]) {
    const m = new THREE.Mesh(geometry, material);
    m.position.set(...position);
    m.rotation.set(...rotation);
    m.castShadow = true;
    m.receiveShadow = true;
    worker.add(m);
    return m;
  }

  const torso = mesh(new THREE.CapsuleGeometry(0.58, 1.1, 8, 20), suit, [0, 1.65, 0]);
  torso.scale.z = 0.78;
  const head = mesh(new THREE.SphereGeometry(0.46, 32, 24), skin, [0, 2.75, 0.02]);
  head.scale.set(0.92, 1.08, 0.9);
  const hair = mesh(new THREE.SphereGeometry(0.48, 28, 18, 0, Math.PI * 2, 0, Math.PI * 0.53), dark, [0, 2.9, -0.01]);
  const visor = mesh(new THREE.BoxGeometry(0.66, 0.08, 0.08), glowBlue, [0, 2.76, 0.42]);
  visor.rotation.x = -0.06;
  const core = mesh(new THREE.SphereGeometry(0.12, 24, 18), glowGreen, [0, 1.78, 0.52]);

  const leftArmPivot = new THREE.Group();
  leftArmPivot.position.set(-0.62, 2.08, 0);
  worker.add(leftArmPivot);
  const leftArm = new THREE.Mesh(new THREE.CapsuleGeometry(0.15, 0.82, 8, 16), suit);
  leftArm.position.y = -0.45;
  leftArm.rotation.z = 0.2;
  leftArm.castShadow = true;
  leftArmPivot.add(leftArm);

  const rightArmPivot = new THREE.Group();
  rightArmPivot.position.set(0.62, 2.08, 0);
  worker.add(rightArmPivot);
  const rightArm = new THREE.Mesh(new THREE.CapsuleGeometry(0.15, 0.82, 8, 16), suit);
  rightArm.position.y = -0.45;
  rightArm.rotation.z = -0.22;
  rightArm.castShadow = true;
  rightArmPivot.add(rightArm);

  mesh(new THREE.CapsuleGeometry(0.18, 0.9, 8, 16), dark, [-0.26, 0.63, 0]);
  mesh(new THREE.CapsuleGeometry(0.18, 0.9, 8, 16), dark, [0.26, 0.63, 0]);

  const desk = mesh(new THREE.BoxGeometry(3.4, 0.16, 1.45), new THREE.MeshStandardMaterial({ color: 0x1f3148, metalness: 0.62, roughness: 0.38 }), [0, 1.02, 1.15]);
  desk.castShadow = true;
  mesh(new THREE.BoxGeometry(0.14, 1.0, 0.14), dark, [-1.32, 0.5, 1.12]);
  mesh(new THREE.BoxGeometry(0.14, 1.0, 0.14), dark, [1.32, 0.5, 1.12]);

  const monitorGroup = new THREE.Group();
  monitorGroup.position.set(0.82, 1.72, 0.9);
  monitorGroup.rotation.y = -0.22;
  worker.add(monitorGroup);
  const monitor = new THREE.Mesh(new THREE.BoxGeometry(1.65, 1.02, 0.1), dark);
  monitor.castShadow = true;
  monitorGroup.add(monitor);
  const screen = new THREE.Mesh(new THREE.PlaneGeometry(1.48, 0.84), glowBlue);
  screen.position.z = 0.056;
  monitorGroup.add(screen);
  const keyboard = mesh(new THREE.BoxGeometry(1.35, 0.07, 0.45), dark, [0.4, 1.16, 1.45], [-0.12, -0.12, 0]);

  const halo = new THREE.Mesh(
    new THREE.TorusGeometry(1.65, 0.02, 12, 96),
    glowBlue
  );
  halo.rotation.x = Math.PI / 2;
  halo.position.y = 1.76;
  worker.add(halo);

  const particlesGeometry = new THREE.BufferGeometry();
  const particleCount = 90;
  const positions = new Float32Array(particleCount * 3);
  for (let i = 0; i < particleCount; i += 1) {
    positions[i * 3] = (Math.random() - 0.5) * 7;
    positions[i * 3 + 1] = Math.random() * 4.8;
    positions[i * 3 + 2] = (Math.random() - 0.5) * 5;
  }
  particlesGeometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  const particles = new THREE.Points(
    particlesGeometry,
    new THREE.PointsMaterial({ color: 0x58a6ff, size: 0.035, transparent: true, opacity: 0.72 })
  );
  scene.add(particles);

  let dragging = false;
  let lastX = 0;
  let lastY = 0;
  let targetRotationY = 0;
  let targetRotationX = 0;

  renderer.domElement.addEventListener('pointerdown', (event) => {
    dragging = true;
    lastX = event.clientX;
    lastY = event.clientY;
    renderer.domElement.setPointerCapture(event.pointerId);
  });
  renderer.domElement.addEventListener('pointermove', (event) => {
    if (!dragging) return;
    targetRotationY += (event.clientX - lastX) * 0.008;
    targetRotationX += (event.clientY - lastY) * 0.004;
    targetRotationX = Math.max(-0.25, Math.min(0.25, targetRotationX));
    lastX = event.clientX;
    lastY = event.clientY;
  });
  renderer.domElement.addEventListener('pointerup', () => { dragging = false; });
  renderer.domElement.addEventListener('pointercancel', () => { dragging = false; });

  function resize() {
    const width = Math.max(container.clientWidth, 240);
    const height = Math.max(container.clientHeight, 260);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(container);
  resize();

  const clock = new THREE.Clock();
  function animate() {
    const t = clock.getElapsedTime();
    const status = document.getElementById('agent-status');
    const isRunning = status?.classList.contains('badge-running');
    const speed = isRunning ? 5.2 : 2.2;

    worker.rotation.y += (targetRotationY - worker.rotation.y) * 0.08;
    worker.rotation.x += (targetRotationX - worker.rotation.x) * 0.08;
    worker.position.y = Math.sin(t * 1.6) * 0.035;
    head.rotation.y = Math.sin(t * 0.8) * 0.08;
    rightArmPivot.rotation.x = -0.45 + Math.sin(t * speed) * 0.18;
    leftArmPivot.rotation.x = -0.28 + Math.cos(t * speed * 0.92) * 0.11;
    halo.rotation.z = t * 0.32;
    core.scale.setScalar(1 + Math.sin(t * 3.2) * 0.16);
    screen.material.emissiveIntensity = 2.2 + Math.sin(t * 4) * 0.55;
    particles.rotation.y = t * 0.035;

    renderer.render(scene, camera);
    requestAnimationFrame(animate);
  }
  animate();
})();
