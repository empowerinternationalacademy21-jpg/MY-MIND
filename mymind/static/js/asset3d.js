/* 3D model viewer for approved AI 3D friends (GLB). Uses window.MM3D (static/vendor/three-gltf.min.js).
   One WebGL context at a time: a model loads only when tapped (or when data-autostart is set), and is disposed when closed. */
(function () {
  "use strict";
  var M = window.MM3D;
  if (!M) return;
  var active = null;
  var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function webglOk() {
    try { var c = document.createElement("canvas"); return !!(c.getContext("webgl2") || c.getContext("webgl")); } catch (e) { return false; }
  }

  function Viewer(host) {
    this.host = host;
    this.glb = host.dataset.glb;
    this.clips = {};
    try { var names = JSON.parse(host.dataset.clips || "[]"); names.forEach(function (n) { this.clips[n] = host.dataset.glb.replace(/\/glb$/, "/" + n); }, this); } catch (e) {}
    this.stage = host.querySelector(".a3d-stage");
    this.start = host.querySelector(".a3d-start");
    this.dead = false;
  }

  Viewer.prototype.open = function () {
    var self = this;
    if (active && active !== this) active.close();
    active = this;
    if (!webglOk()) { this.msg("3D isn't available on this device."); return; }
    this.stage.hidden = false;
    if (this.start) this.start.hidden = true;
    this.msg("Loading…");
    var w = Math.max(240, this.stage.clientWidth || 320), h = Math.round(w * 0.9);
    var r = this.renderer = new M.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "default" });
    r.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    r.setSize(w, h);
    r.outputColorSpace = M.SRGBColorSpace;
    r.toneMapping = M.ACESFilmicToneMapping; r.toneMappingExposure = 0.95;
    r.shadowMap.enabled = true; r.shadowMap.type = M.PCFSoftShadowMap;
    r.domElement.setAttribute("role", "img");
    r.domElement.setAttribute("aria-label", (this.host.dataset.name || "3D friend") + " (3D model, drag to turn)");
    r.domElement.addEventListener("webglcontextlost", function (e) { e.preventDefault(); self.msg("The 3D view paused. Tap to try again."); self.close(true); });
    var scene = this.scene = new M.Scene();
    var pm = new M.PMREMGenerator(r);
    scene.environment = pm.fromScene(new M.RoomEnvironment(), 0.04).texture; scene.environmentIntensity = 0.5;    // procedural studio lighting: no HDR file to download
    var cam = this.camera = new M.PerspectiveCamera(35, w / h, 0.05, 100);
    var key = new M.DirectionalLight(0xffffff, 1.0); key.position.set(2.5, 4, 3); key.castShadow = true; key.shadow.mapSize.set(1024, 1024);
    scene.add(key, new M.HemisphereLight(0xffffff, 0xb8c4d8, 0.3));
    var ground = this.ground = new M.Mesh(new M.PlaneGeometry(10, 10), new M.ShadowMaterial({ opacity: 0.22 }));
    ground.rotation.x = -Math.PI / 2; ground.receiveShadow = true; scene.add(ground);
    var ctl = this.controls = new M.OrbitControls(cam, r.domElement);
    ctl.enableDamping = true; ctl.enablePan = false; ctl.minPolarAngle = 0.5; ctl.maxPolarAngle = 1.6; ctl.autoRotate = !reduced; ctl.autoRotateSpeed = 1.2;
    this.clock = new M.Clock();
    this.loader = new M.GLTFLoader();
    var draco = new M.DRACOLoader(); draco.setDecoderPath("/static/vendor/draco/"); this.loader.setDRACOLoader(draco); this.draco = draco;
    this.loader.setMeshoptDecoder(M.MeshoptDecoder);
    this.stage.replaceChildren(r.domElement);
    this.buttons();
    this.load(this.glb, null, true);
    var loop = function () {
      if (self.dead) return;
      self.raf = requestAnimationFrame(loop);
      var dt = self.clock.getDelta();
      if (self.mixer && !reduced) self.mixer.update(dt);
      ctl.update(); r.render(scene, cam);
    };
    loop();
  };

  Viewer.prototype.msg = function (t) {
    var p = this.stage.querySelector(".a3d-msg");
    if (!p) { p = document.createElement("p"); p.className = "a3d-msg small muted"; this.stage.prepend(p); this.stage.hidden = false; }
    p.textContent = t;
    if (!t) p.remove();
  };

  Viewer.prototype.buttons = function () {
    var self = this, names = Object.keys(this.clips);
    if (!names.length) return;
    var bar = document.createElement("div"); bar.className = "a3d-clips"; bar.setAttribute("role", "group"); bar.setAttribute("aria-label", "Animations");
    [["Pose", null]].concat(names.map(function (n) { return [n.charAt(0).toUpperCase() + n.slice(1), n]; })).forEach(function (pair) {
      var b = document.createElement("button"); b.type = "button"; b.className = "chip"; b.textContent = pair[0];
      b.addEventListener("click", function () {
        bar.querySelectorAll("button").forEach(function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
        self.load(pair[1] ? self.clips[pair[1]] : self.glb, pair[1], false);
      });
      bar.appendChild(b);
    });
    this.stage.appendChild(bar);
  };

  Viewer.prototype.load = function (url, clip, first) {
    var self = this;
    this.loader.load(url, function (gltf) {
      if (self.dead) return;
      if (self.model) { self.scene.remove(self.model); }
      var m = self.model = gltf.scene;
      m.traverse(function (o) { if (o.isMesh) { o.castShadow = true; } });
      var box = new M.Box3().setFromObject(m), size = box.getSize(new M.Vector3()), ctr = box.getCenter(new M.Vector3());
      var s = 1.6 / Math.max(size.x, size.y, size.z, 0.001);
      m.scale.setScalar(s); m.position.sub(ctr.multiplyScalar(s)); m.position.y += (size.y * s) / 2;   // stand on the ground
      self.scene.add(m);
      self.ground.position.y = 0;
      if (first) {
        self.camera.position.set(0, 1.1, 3.9); self.controls.target.set(0, 0.8, 0); self.controls.update();
        self.msg("");
      }
      self.mixer = null;
      if (clip && gltf.animations && gltf.animations.length) {
        self.mixer = new M.AnimationMixer(m);
        var a = self.mixer.clipAction(gltf.animations[0]); a.setLoop(M.LoopRepeat, Infinity); a.play();
        self.controls.autoRotate = false;
      } else { self.controls.autoRotate = !reduced; }
    }, undefined, function () { self.msg("This friend couldn't be loaded right now."); });
  };

  Viewer.prototype.close = function (keepMsg) {
    this.dead = true;
    if (this.raf) cancelAnimationFrame(this.raf);
    try { if (this.controls) this.controls.dispose(); if (this.draco) this.draco.dispose(); } catch (e) {}
    try { if (this.scene) this.scene.traverse(function (o) { if (o.geometry) o.geometry.dispose(); if (o.material) { [].concat(o.material).forEach(function (mt) { Object.keys(mt).forEach(function (k) { if (mt[k] && mt[k].isTexture) mt[k].dispose(); }); mt.dispose(); }); } }); } catch (e) {}
    try { if (this.renderer) { this.renderer.dispose(); this.renderer.forceContextLoss(); } } catch (e) {}
    if (!keepMsg) this.stage.replaceChildren();
    this.stage.hidden = !keepMsg;
    if (this.start) this.start.hidden = false;
    this.host._viewer = null;
    if (active === this) active = null;
  };

  function scan(root) {
    (root || document).querySelectorAll("[data-asset3d]").forEach(function (host) {
      if (host._wired) return;
      host._wired = true;
      var open = function () { if (host._viewer) return; var v = host._viewer = new Viewer(host); v.open(); };
      var start = host.querySelector(".a3d-start");
      if (start) start.addEventListener("click", open);
      if (host.hasAttribute("data-autostart")) open();
    });
  }
  window.MMAsset3D = { scan: scan, closeAll: function () { if (active) active.close(); } };
  scan(document);
  document.addEventListener("visibilitychange", function () { if (document.hidden && active) active.close(); });   // free the GPU when the tab is hidden
})();
