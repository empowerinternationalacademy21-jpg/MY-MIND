/* My World: procedural 3D island scene (Three.js via window.MM3D). No external art or model files: every island, landmark and prop is built
   from primitives and coloured from the theme palette. Exposed as MMWorld.createScene(host, data, hooks). */
(function () {
  "use strict";
  var M = window.MM3D;
  var NS = (window.MMWorld = window.MMWorld || {});
  if (!M) return;

  var SX = 0.28, SZ = 0.40, R = 2.3, TILT = 0.8;           // map grid -> world units, island radius, camera tilt (radians above the horizon)
  var FOV = 38;

  function hash(s) { var h = 2166136261; for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
  function rng(seed) { var a = seed >>> 0; return function () { a |= 0; a = (a + 0x6D2B79F5) | 0; var t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
  function ease(t) { return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2; }

  NS.createScene = function (host, data, hooks) {
    hooks = hooks || {};
    var disposed = false, animOn = true, dirty = true;
    var theme = data.theme, pal = theme.palette;
    var matCache = {}, geoms = [], floaters = [], islands = {}, pop = [], clouds = [], rings = [];
    var low = false;

    // ------------------------------------------------------------------ renderer
    var renderer = new M.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "default" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = M.SRGBColorSpace;
    renderer.toneMapping = M.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05;
    renderer.shadowMap.enabled = true; renderer.shadowMap.type = M.PCFSoftShadowMap;
    var canvas = renderer.domElement;
    canvas.className = "w3d-canvas"; canvas.tabIndex = 0;
    canvas.setAttribute("role", "application");
    canvas.setAttribute("aria-label", "Your world map. Drag to move, pinch or use plus and minus to zoom. Use the list of places to open one with the keyboard.");
    host.prepend(canvas);
    canvas.addEventListener("webglcontextlost", function (e) { e.preventDefault(); if (!disposed && hooks.onContextLost) hooks.onContextLost(); });    // our own dispose() also loses the context: not an error

    var scene = new M.Scene();
    var camera = new M.PerspectiveCamera(FOV, 1, 0.5, 220);
    var hemi = new M.HemisphereLight(0xffffff, 0x9bb4d6, 1.0); scene.add(hemi);
    var sun = new M.DirectionalLight(0xffffff, 1.25);
    sun.position.set(9, 16, 7); sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048);
    var sc = sun.shadow.camera; sc.left = -26; sc.right = 26; sc.top = 24; sc.bottom = -24; sc.near = 1; sc.far = 60; sun.shadow.bias = -0.0006;
    scene.add(sun);

    // ------------------------------------------------------------------ materials
    function std(color, o) {
      var key = color + (o ? JSON.stringify(o) : "");
      if (!matCache[key]) matCache[key] = new M.MeshStandardMaterial(Object.assign({ color: color, roughness: 0.72, metalness: 0.02 }, o || {}));
      return matCache[key];
    }
    function geo(g) { geoms.push(g); return g; }
    function place(m, x, y, z, shadow) { m.position.set(x || 0, y || 0, z || 0); m.castShadow = shadow !== false; m.receiveShadow = true; return m; }
    function box(w, h, d, c, x, y, z, o) { return place(new M.Mesh(geo(new M.BoxGeometry(w, h, d)), std(c, o)), x, y, z); }
    function cyl(rt, rb, h, c, x, y, z, seg, o) { return place(new M.Mesh(geo(new M.CylinderGeometry(rt, rb, h, seg || 20)), std(c, o)), x, y, z); }
    function cone(r, h, c, x, y, z, seg, o) { return place(new M.Mesh(geo(new M.ConeGeometry(r, h, seg || 20)), std(c, o)), x, y, z); }
    function sph(r, c, x, y, z, o) { return place(new M.Mesh(geo(new M.SphereGeometry(r, 20, 14)), std(c, o)), x, y, z); }
    function tor(r, t, c, x, y, z, arc, o) { return place(new M.Mesh(geo(new M.TorusGeometry(r, t, 10, 28, arc || Math.PI * 2)), std(c, o)), x, y, z); }
    function grp() { var g = new M.Group(); for (var i = 0; i < arguments.length; i++) g.add(arguments[i]); return g; }
    function rot(m, x, y, z) { m.rotation.set(x || 0, y || 0, z || 0); return m; }

    // ------------------------------------------------------------------ landmarks (one per stop)
    function tree(x, z, s, c1, c2) {
      var t = grp(cyl(0.07, 0.1, 0.5, "#8a5a3c", 0, 0.25, 0, 8), cone(0.42, 0.7, c1 || "#3fa34d", 0, 0.8, 0, 10), cone(0.32, 0.6, c2 || "#4cbb5a", 0, 1.2, 0, 10));
      t.position.set(x, 0, z); t.scale.setScalar(s || 1); return t;
    }
    var LANDMARKS = {
      home: function (g, a) {
        g.add(box(1.3, 0.9, 1.1, "#fff4dc", 0, 0.45, 0), rot(cone(1.1, 0.7, a, 0, 1.25, 0, 4), 0, Math.PI / 4, 0), box(0.28, 0.5, 0.05, "#8a5a3c", 0, 0.25, 0.56),
          box(0.3, 0.3, 0.05, "#a8d8ff", -0.4, 0.58, 0.56), box(0.3, 0.3, 0.05, "#a8d8ff", 0.4, 0.58, 0.56), box(0.2, 0.5, 0.2, "#b9674a", 0.42, 1.5, -0.2));
      },
      pictures: function (g) {
        var cols = ["#ff8fa3", "#7ec8ff", "#ffd36b"];
        for (var i = -1; i <= 1; i++) {
          var e = grp(box(0.74, 0.94, 0.06, "#ffffff", 0, 0.8, 0), box(0.6, 0.78, 0.07, cols[i + 1], 0, 0.8, 0.01), cyl(0.03, 0.03, 0.55, "#8a5a3c", -0.22, 0.27, -0.12, 6), cyl(0.03, 0.03, 0.55, "#8a5a3c", 0.22, 0.27, -0.12, 6));
          e.position.set(i * 0.85, 0, i * i * 0.18 - 0.2); e.rotation.y = -i * 0.35; g.add(e);
        }
      },
      videos: function (g) {
        g.add(box(1.5, 0.95, 0.15, "#2b3350", 0, 1.0, 0), box(1.34, 0.8, 0.05, "#7ec8ff", 0, 1.0, 0.09), rot(cone(0.24, 0.4, "#ffffff", 0.04, 1.0, 0.14, 3), 0, 0, -Math.PI / 2),
          cyl(0.1, 0.1, 0.35, "#2b3350", 0, 0.2, 0, 10), cyl(0.5, 0.55, 0.06, "#2b3350", 0, 0.03, 0, 20));
      },
      shots: function (g) {
        g.add(box(0.78, 1.5, 0.1, "#2b3350", 0, 0.95, 0), box(0.66, 1.34, 0.05, "#c9a8ff", 0, 0.95, 0.06), rot(cone(0.22, 0.36, "#ffffff", 0.03, 0.95, 0.1, 3), 0, 0, -Math.PI / 2),
          cyl(0.08, 0.08, 0.4, "#2b3350", 0, 0.2, 0, 10), cyl(0.45, 0.5, 0.06, "#2b3350", 0, 0.03, 0, 20));
      },
      music: function (g, a) {
        g.add(cyl(0.62, 0.62, 0.72, a, 0, 0.4, 0, 28), rot(tor(0.62, 0.05, "#ffffff", 0, 0.77, 0), Math.PI / 2, 0, 0), rot(tor(0.62, 0.05, "#ffffff", 0, 0.04, 0), Math.PI / 2, 0, 0),
          cyl(0.58, 0.58, 0.04, "#fff7e0", 0, 0.76, 0, 28), rot(cyl(0.03, 0.03, 0.8, "#d9a066", -0.2, 1.0, 0.1, 6), 0.3, 0, 0.5), rot(cyl(0.03, 0.03, 0.8, "#d9a066", 0.2, 1.0, 0.1, 6), 0.3, 0, -0.5));
        [[-0.9, 1.5, "#ff8fa3"], [0.9, 1.8, "#7ec8ff"]].forEach(function (n) {
          var note = grp(sph(0.15, n[2], 0, 0, 0), cyl(0.025, 0.025, 0.5, n[2], 0.13, 0.25, 0, 6), box(0.22, 0.07, 0.03, n[2], 0.24, 0.5, 0));
          note.position.set(n[0], n[1], 0.2); g.add(note); floaters.push({ o: note, y: n[1], s: 1.4 + Math.abs(n[0]), p: n[0] * 3 });
        });
      },
      sports: function (g, a, th) {
        if (th === "basketball") {
          g.add(cyl(0.05, 0.05, 1.7, "#cfd6e4", -0.6, 0.85, -0.2, 8), box(0.95, 0.62, 0.06, "#ffffff", -0.6, 1.62, 0.12), rot(tor(0.22, 0.03, "#ff6a2b", -0.6, 1.4, 0.38), Math.PI / 2, 0, 0),
            sph(0.3, "#ff8a2b", 0.55, 0.3, 0.55));
        } else {
          g.add(cyl(0.04, 0.04, 1.0, "#ffffff", -0.9, 0.5, 0, 8), cyl(0.04, 0.04, 1.0, "#ffffff", 0.9, 0.5, 0, 8), rot(cyl(0.04, 0.04, 1.84, "#ffffff", 0, 1.0, 0, 8), 0, 0, Math.PI / 2),
            box(1.8, 1.0, 0.5, "#ffffff", 0, 0.5, -0.28, { transparent: true, opacity: 0.16 }), sph(0.3, "#ffffff", 0.45, 0.3, 0.8),
            place(new M.Mesh(geo(new M.DodecahedronGeometry(0.14)), std("#2b3350")), 0.45, 0.3, 1.06));
        }
      },
      food: function (g) {
        var c = grp(rot(cone(0.46, 1.1, "#e3b36b", 0, 0.55, 0, 18), Math.PI, 0, 0), sph(0.52, "#ff9fb5", 0, 1.22, 0), sph(0.44, "#fff2d6", 0, 1.78, 0), sph(0.1, "#e63946", 0, 2.2, 0));
        c.scale.setScalar(0.85); g.add(c);
      },
      colors: function (g) {
        g.add(rot(box(0.7, 0.7, 0.7, "#ff6b6b", -0.75, 0.35, 0.25), 0, 0.3, 0), sph(0.4, "#4dabf7", 0.1, 0.4, 0.6), cone(0.4, 0.8, "#ffd43b", 0.85, 0.4, 0.1, 4), rot(tor(0.32, 0.13, "#51cf66", 0.3, 0.14, -0.1), Math.PI / 2, 0, 0));
        ["#ff6b6b", "#ff922b", "#ffd43b", "#51cf66", "#4dabf7", "#9775fa"].forEach(function (c, i) { g.add(tor(1.05 - i * 0.1, 0.055, c, 0, 0.02, -0.95, Math.PI)); });
      },
      nature: function (g) {
        g.add(tree(-0.7, -0.2, 1.15), tree(0.75, 0.1, 0.95, "#2f9a56", "#3fb36a"), tree(0.1, -0.85, 0.8, "#45a049", "#58b85c"),
          place(new M.Mesh(geo(new M.IcosahedronGeometry(0.28, 0)), std("#9aa3ad", { flatShading: true })), 0.15, 0.2, 0.6));
        [["#ff8fa3", -0.2, 0.9], ["#ffd36b", -0.5, 0.75], ["#c9a8ff", 0.5, 0.7]].forEach(function (f) { g.add(cyl(0.015, 0.015, 0.3, "#3fa34d", f[1], 0.15, f[2], 5), sph(0.09, f[0], f[1], 0.34, f[2])); });
      },
      animals: function (g) {
        var b = "#c98b4a", d = "#8a5a3c";
        var dog = grp(rot(place(new M.Mesh(geo(new M.CapsuleGeometry(0.27, 0.55, 6, 14)), std(b)), 0, 0.55, 0), 0, 0, Math.PI / 2), sph(0.3, b, 0.62, 0.8, 0), box(0.28, 0.2, 0.26, "#e8c08a", 0.9, 0.72, 0),
          sph(0.05, "#222", 0.78, 0.9, 0.14), sph(0.05, "#222", 0.78, 0.9, -0.14), box(0.1, 0.3, 0.2, d, 0.55, 1.0, 0.24), box(0.1, 0.3, 0.2, d, 0.55, 1.0, -0.24),
          rot(cyl(0.05, 0.03, 0.5, b, -0.7, 0.8, 0, 6), 0, 0, 0.9), sph(0.05, "#222", 1.04, 0.76, 0));
        [[-0.3, 0.16], [-0.3, -0.16], [0.3, 0.16], [0.3, -0.16]].forEach(function (l) { dog.add(cyl(0.07, 0.07, 0.4, b, l[0], 0.2, l[1], 8)); });
        dog.rotation.y = -0.5; dog.scale.setScalar(1.05); g.add(dog);
        g.add(cyl(0.2, 0.2, 0.09, "#ff8fa3", -0.85, 0.05, 0.9, 16));
      },
      vehicles: function (g, a) {
        var car = grp(box(1.6, 0.4, 0.85, a, 0, 0.5, 0), box(0.85, 0.38, 0.75, "#cfe6ff", -0.1, 0.88, 0), box(0.02, 0.2, 0.6, "#2b3350", 0.34, 0.9, 0), sph(0.09, "#ffe066", 0.82, 0.5, 0.28), sph(0.09, "#ffe066", 0.82, 0.5, -0.28));
        [[-0.5, 0.45], [-0.5, -0.45], [0.5, 0.45], [0.5, -0.45]].forEach(function (w) { car.add(rot(cyl(0.24, 0.24, 0.14, "#2b3350", w[0], 0.24, w[1], 16), Math.PI / 2, 0, 0)); });
        car.rotation.y = -0.4; g.add(car);
      },
      art: function (g) {
        g.add(rot(cyl(0.03, 0.03, 1.5, "#8a5a3c", -0.45, 0.72, -0.2, 6), 0.15, 0, 0.18), rot(cyl(0.03, 0.03, 1.5, "#8a5a3c", 0.45, 0.72, -0.2, 6), 0.15, 0, -0.18), rot(cyl(0.03, 0.03, 1.4, "#8a5a3c", 0, 0.7, -0.55, 6), -0.3, 0, 0),
          box(1.0, 0.75, 0.05, "#ffffff", 0, 1.05, 0.05));
        [["#ff6b6b", -0.25, 1.2], ["#4dabf7", 0.2, 1.0], ["#ffd43b", -0.05, 0.9], ["#51cf66", 0.3, 1.25]].forEach(function (d) { g.add(sph(0.11, d[0], d[1], d[2], 0.1)); });
        g.add(cyl(0.38, 0.38, 0.05, "#f1d9a8", 0.95, 0.04, 0.6, 20), sph(0.08, "#ff6b6b", 0.8, 0.1, 0.6), sph(0.08, "#4dabf7", 1.0, 0.1, 0.5), sph(0.08, "#51cf66", 1.05, 0.1, 0.72));
      }
    };

    // ------------------------------------------------------------------ small decorative props (counts come from the child's own evidence)
    var PROPS = {
      balls: function (r) { return sph(0.13, r() > 0.5 ? "#ffffff" : "#ffb347", 0, 0.13, 0); },
      notes: function (r) { var c = ["#ff8fa3", "#7ec8ff", "#c9a8ff"][(r() * 3) | 0]; return grp(sph(0.08, c, 0, 0.08, 0), cyl(0.02, 0.02, 0.32, c, 0.07, 0.24, 0, 5)); },
      treats: function (r) { var c = ["#ff9fb5", "#fff2d6", "#ffd36b"][(r() * 3) | 0]; return grp(rot(cone(0.1, 0.26, "#e3b36b", 0, 0.13, 0, 10), Math.PI, 0, 0), sph(0.12, c, 0, 0.33, 0)); },
      shapes: function (r) { var c = ["#ff6b6b", "#4dabf7", "#ffd43b", "#51cf66", "#9775fa"][(r() * 5) | 0], k = (r() * 3) | 0; return k === 0 ? box(0.2, 0.2, 0.2, c, 0, 0.1, 0) : k === 1 ? sph(0.12, c, 0, 0.12, 0) : cone(0.13, 0.26, c, 0, 0.13, 0, 4); },
      trees: function (r) { return tree(0, 0, 0.42 + r() * 0.25); },
      paws: function () { var g = grp(cyl(0.1, 0.1, 0.03, "#ff8fa3", 0, 0.02, 0, 12)); [-0.09, 0, 0.09].forEach(function (x, i) { g.add(cyl(0.04, 0.04, 0.03, "#ff8fa3", x, 0.02, -0.12 - (i === 1 ? 0.03 : 0), 8)); }); return g; },
      cones: function () { return grp(cone(0.1, 0.3, "#ff8a2b", 0, 0.17, 0, 12), box(0.24, 0.03, 0.24, "#ff8a2b", 0, 0.015, 0)); },
      paint: function (r) { var c = ["#ff6b6b", "#4dabf7", "#ffd43b", "#51cf66"][(r() * 4) | 0]; var s = sph(0.14, c, 0, 0.05, 0); s.scale.y = 0.4; return s; },
      flowers: function (r) { var c = ["#ff8fa3", "#ffd36b", "#c9a8ff", "#ffffff"][(r() * 4) | 0]; return grp(cyl(0.015, 0.015, 0.22, "#3fa34d", 0, 0.11, 0, 5), sph(0.07, c, 0, 0.25, 0)); }
    };

    // ------------------------------------------------------------------ islands
    function worldPos(s) { return { x: (s.x - 50) * SX, z: (s.y - 50) * SZ }; }

    function makeIsland(s, idx) {
      var g = new M.Group(), r = rng(hash(s.key)), ph = r() * 6.28;
      var grass = new M.Color(pal.grass).lerp(new M.Color(s.color), 0.14);
      var g1 = geo(new M.CylinderGeometry(R, R * 0.96, 0.5, 36, 1)), p = g1.attributes.position;
      var f1 = r() * 6, f2 = r() * 6;
      for (var i = 0; i < p.count; i++) {                              // organic outline: radial wobble shared by top and side vertices
        var x = p.getX(i), z = p.getZ(i), a = Math.atan2(z, x), k = 1 + 0.055 * Math.sin(3 * a + f1) + 0.035 * Math.sin(5 * a + f2);
        p.setX(i, x * k); p.setZ(i, z * k);
      }
      g1.computeVertexNormals();
      var top = new M.Mesh(g1, [std(pal.sand, { roughness: 0.9 }), std(grass.getStyle(), { roughness: 0.85 }), std("#a98a62")]);
      top.position.y = -0.25; top.receiveShadow = true; top.castShadow = true; g.add(top);
      var g2 = geo(new M.ConeGeometry(R * 0.93, 2.3, 9, 1)), q = g2.attributes.position;
      for (var j = 0; j < q.count; j++) { var yy = q.getY(j); if (yy > -1) { var jit = 1 + (r() - 0.5) * 0.18; q.setX(j, q.getX(j) * jit); q.setZ(j, q.getZ(j) * jit); } }
      g2.computeVertexNormals();
      var under = new M.Mesh(g2, std("#8c7a68", { flatShading: true, roughness: 1 }));
      under.rotation.x = Math.PI; under.position.y = -1.4; under.castShadow = false; g.add(under);
      var lm = new M.Group(); lm.position.set(0, 0, 0);
      (LANDMARKS[s.key] || function () {})(lm, s.color, theme.key);
      g.add(lm);
      // props
      var props = new M.Group(), n = s.decor.count, pr = rng(hash(s.key + "decor")), placed = [];
      var maker = PROPS[s.decor.kind] || PROPS.flowers;
      for (var t = 0, tries = 0; t < n && tries < 80; tries++) {
        var ang = pr() * 6.283, rad = 1.2 + pr() * 0.85, px = Math.cos(ang) * rad, pz = Math.sin(ang) * rad, ok = true;
        for (var k2 = 0; k2 < placed.length; k2++) { var dx = placed[k2][0] - px, dz = placed[k2][1] - pz; if (dx * dx + dz * dz < 0.2) { ok = false; break; } }
        if (!ok) continue;
        placed.push([px, pz]); t++;
        var o = maker(pr); o.position.set(px, 0, pz); o.rotation.y = pr() * 6.28; o.userData.target = o.scale.x; props.add(o);
      }
      g.add(props);
      var pos = worldPos(s);
      g.position.set(pos.x, 0, pos.z);
      g.userData = { key: s.key, phase: ph, props: props, lm: lm, top: top, under: under };
      // foam ring on the water
      var ring = new M.Mesh(geo(new M.RingGeometry(R * 1.02, R * 1.22, 44)), new M.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.38, depthWrite: false }));
      ring.rotation.x = -Math.PI / 2; ring.position.set(pos.x, -0.82, pos.z); scene.add(ring); rings.push({ m: ring, p: ph });
      g.userData.ring = ring;
      g.scale.setScalar(0.001); pop.push({ g: g, t0: 0.05 + idx * 0.07 });
      islands[s.key] = g; scene.add(g);
      return g;
    }

    function makeBridge(a, b) {
      var A = islands[a], B = islands[b]; if (!A || !B) return;
      var ax = A.position.x, az = A.position.z, bx = B.position.x, bz = B.position.z;
      var dx = bx - ax, dz = bz - az, L = Math.sqrt(dx * dx + dz * dz), ux = dx / L, uz = dz / L;
      var sx = ax + ux * (R * 0.92), sz = az + uz * (R * 0.92), ex = bx - ux * (R * 0.92), ez = bz - uz * (R * 0.92);
      var len = Math.sqrt((ex - sx) * (ex - sx) + (ez - sz) * (ez - sz)), count = Math.max(3, Math.floor(len / 0.34)), yaw = Math.atan2(dx, dz);
      var bg = new M.Group();
      for (var i = 0; i <= count; i++) {
        var t = i / count, x = sx + (ex - sx) * t, z = sz + (ez - sz) * t, y = -Math.sin(t * Math.PI) * 0.4 - 0.04;
        var plank = box(0.74, 0.06, 0.26, i % 2 ? "#c9955a" : "#b9824a", x, y, z); plank.rotation.y = yaw; bg.add(plank);
        if (i % 3 === 0) {
          [-0.4, 0.4].forEach(function (side) { var post = cyl(0.035, 0.035, 0.36, "#8a5a3c", x + Math.cos(yaw) * side, y + 0.2, z - Math.sin(yaw) * side, 6); bg.add(post); });
        }
      }
      scene.add(bg);
    }

    // ------------------------------------------------------------------ water + sky + clouds
    var waterMat = new M.ShaderMaterial({
      transparent: true, depthWrite: false,
      uniforms: { uTime: { value: 0 }, uA: { value: new M.Color(pal.water[0]) }, uB: { value: new M.Color(pal.water[1]) } },
      vertexShader: "uniform float uTime; varying vec3 vP; void main(){ vec3 p=position; float w=sin(p.x*0.35+uTime*0.9)*0.5+cos(p.y*0.3+uTime*0.7)*0.5; p.z+=w*0.1; vP=p; gl_Position=projectionMatrix*modelViewMatrix*vec4(p,1.0); }",
      fragmentShader: "uniform vec3 uA; uniform vec3 uB; uniform float uTime; varying vec3 vP; void main(){ float d=length(vP.xy); float k=smoothstep(4.0,40.0,d); vec3 c=mix(uB,uA,k*0.55); float s=sin(vP.x*1.1+uTime*0.9)*sin(vP.y*1.0-uTime*0.8); c+=smoothstep(0.93,1.0,s)*0.08; float a=1.0-smoothstep(42.0,78.0,d); gl_FragColor=vec4(c,a*0.97); }"
    });
    var water = new M.Mesh(geo(new M.PlaneGeometry(170, 170, 48, 48)), waterMat);
    water.rotation.x = -Math.PI / 2; water.position.y = -0.9; scene.add(water);

    var cloudMat = new M.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.9, depthWrite: false });
    function makeCloud(r) {
      var c = new M.Group(), n = 3 + ((r() * 3) | 0);
      for (var i = 0; i < n; i++) { var s = new M.Mesh(geo(new M.SphereGeometry(0.9 + r() * 0.8, 14, 10)), cloudMat); s.position.set(i * 1.2 - n * 0.55, r() * 0.4, (r() - 0.5) * 0.8); s.scale.y = 0.62; c.add(s); }
      return c;
    }
    var cr = rng(7);
    for (var ci = 0; ci < 8; ci++) { var cl = makeCloud(cr); cl.position.set((cr() - 0.5) * 90, 9 + cr() * 4, -26 - cr() * 16); cl.scale.setScalar(1.3 + cr() * 0.8); cl.userData.speed = 0.25 + cr() * 0.3; scene.add(cl); clouds.push(cl); }

    // ------------------------------------------------------------------ island kit: AI-generated models replace the built-in look piece by piece
    var kit = { landmarks: 0, base: false, failed: 0, pending: 0 }, loaded = [], grow = [], loader = null, envTex = null;
    function getLoader() {
      if (loader) return loader;
      loader = new M.GLTFLoader();
      var draco = new M.DRACOLoader(); draco.setDecoderPath("/static/vendor/draco/"); loader.setDRACOLoader(draco); loader.setMeshoptDecoder(M.MeshoptDecoder);
      return loader;
    }
    var cache = {};
    function loadGLB(url) {
      if (!cache[url]) cache[url] = new Promise(function (res, rej) { getLoader().load(url, function (g) { res(g.scene); }, undefined, rej); });
      return cache[url];
    }
    function environment() {
      if (envTex) return envTex;
      var pm = new M.PMREMGenerator(renderer); envTex = pm.fromScene(new M.RoomEnvironment(), 0.04).texture; pm.dispose(); return envTex;
    }
    function prepare(root) {                            // fresh copy per island, with lighting that suits PBR models and shadows switched on
      var c = root.clone(true);
      c.traverse(function (o) {
        if (!o.isMesh) return;
        o.castShadow = true; o.receiveShadow = true;
        var ms = [].concat(o.material).map(function (m) { var k = m.clone(); k.envMap = environment(); k.envMapIntensity = 0.55; k.needsUpdate = true; loaded.push(k); return k; });
        o.material = Array.isArray(o.material) ? ms : ms[0];
      });
      return c;
    }
    function box3(o) { o.updateMatrixWorld(true); var b = new M.Box3().setFromObject(o); return { b: b, size: b.getSize(new M.Vector3()), c: b.getCenter(new M.Vector3()) }; }
    function clearGroup(g) {
      for (var i = floaters.length - 1; i >= 0; i--) { var o = floaters[i].o, inside = false; while (o) { if (o === g) { inside = true; break; } o = o.parent; } if (inside) floaters.splice(i, 1); }
      while (g.children.length) g.remove(g.children[0]);
    }
    function wrap(m, s, x, y, z) { var w = new M.Group(); m.scale.setScalar(s); m.position.set(x, y, z); w.add(m); return w; }
    function placeLandmark(key, root) {
      var isl = islands[key]; if (!isl) return;
      var c = prepare(root), t = box3(c); if (!(t.size.y > 0)) throw new Error("empty model");
      var s = Math.min(2.2 / t.size.y, 2.8 / Math.max(t.size.x, t.size.z, 0.001));
      var w = wrap(c, s, -t.c.x * s, -t.b.min.y * s, -t.c.z * s);
      clearGroup(isl.userData.lm); isl.userData.lm.add(w); grow.push({ o: w, t0: (performance.now() - born) / 1000 }); w.scale.setScalar(0.01);
      kit.landmarks++;
    }
    function placeBase(root) {
      Object.keys(islands).forEach(function (k) {
        var isl = islands[k], c = prepare(root), t = box3(c); if (!(t.size.y > 0)) throw new Error("empty model");
        var s = (2 * R * 1.04) / Math.max(t.size.x, t.size.z, 0.001);
        var w = wrap(c, s, -t.c.x * s, -t.b.max.y * s, -t.c.z * s);                  // the flat top of the model becomes the island's surface (y = 0)
        isl.remove(isl.userData.top); isl.remove(isl.userData.under); isl.add(w); isl.userData.base = w;
      });
      kit.base = true;
    }
    function loadKit() {
      var jobs = [];
      if (data.island_base) jobs.push(loadGLB(data.island_base.url).then(placeBase).catch(function (e) { kit.failed++; if (window.console) console.warn("island base not loaded", e && e.message); }));
      data.stops.forEach(function (s) {
        if (s.landmark3d) jobs.push(loadGLB(s.landmark3d.url).then(function (r) { placeLandmark(s.key, r); }).catch(function (e) { kit.failed++; if (window.console) console.warn("landmark " + s.key + " not loaded", e && e.message); }));
      });
      kit.pending = jobs.length;
      Promise.all(jobs).then(function () { kit.pending = 0; dirty = true; if (hooks.onKitLoaded) hooks.onKitLoaded(kit); });
    }

    // ------------------------------------------------------------------ build
    host.style.background = "linear-gradient(180deg," + pal.sky[0] + " 0%," + pal.sky[1] + " 62%)";
    if (data.backgrounds && data.backgrounds[0]) { host.style.backgroundImage = 'url("' + encodeURI(data.backgrounds[0]) + '")'; host.style.backgroundSize = "cover"; host.style.backgroundPosition = "center"; }
    hemi.color.set(pal.sky[1]); hemi.groundColor.set(pal.water[0]);
    data.stops.forEach(makeIsland);
    data.bridges.forEach(function (b) { makeBridge(b[0], b[1]); });
    var kitStart = function () { if (data.island_base || data.stops.some(function (s) { return s.landmark3d; })) loadKit(); };

    // ------------------------------------------------------------------ camera controller
    var keys = data.stops.map(function (s) { return worldPos(s); });
    var bb = { x0: Math.min.apply(null, keys.map(function (k) { return k.x; })) - R, x1: Math.max.apply(null, keys.map(function (k) { return k.x; })) + R,
               z0: Math.min.apply(null, keys.map(function (k) { return k.z; })) - R, z1: Math.max.apply(null, keys.map(function (k) { return k.z; })) + R };
    var cam = { tx: 0, tz: 0, d: 30 }, goal = { tx: 0, tz: 0, d: 30 }, saved = null, W = 1, H = 1, focusKey = null;
    function fit() {
      var aspect = W / H, vh = 2 * Math.tan(FOV * Math.PI / 360), cx = (bb.x0 + bb.x1) / 2, cz = (bb.z0 + bb.z1) / 2;
      var needW = (bb.x1 - bb.x0) + 5.5, needD = (bb.z1 - bb.z0) + 6;
      var d = Math.max(needW / (vh * aspect), (needD * Math.sin(TILT)) / vh);
      return { tx: cx, tz: cz + 1.2, d: clamp(d, 14, 80) };
    }
    function clampGoal() {
      goal.tx = clamp(goal.tx, bb.x0, bb.x1); goal.tz = clamp(goal.tz, bb.z0, bb.z1 + 3); goal.d = clamp(goal.d, 9, 72);
    }
    function applyCamera() {
      var cy = Math.sin(TILT) * cam.d, cz = Math.cos(TILT) * cam.d;
      camera.position.set(cam.tx, cy, cam.tz + cz); camera.lookAt(cam.tx, 0, cam.tz);
    }
    function resize() {
      W = Math.max(200, host.clientWidth); H = Math.max(200, host.clientHeight);
      renderer.setSize(W, H, false); canvas.style.width = W + "px"; canvas.style.height = H + "px";
      camera.aspect = W / H; camera.updateProjectionMatrix();
      if (!focusKey && !userMoved) { goal = fit(); cam = Object.assign({}, goal); }
      dirty = true;
    }
    var userMoved = false;
    var ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(resize) : null;
    if (ro) ro.observe(host); else window.addEventListener("resize", resize);

    // pointer: one finger / mouse = pan, two fingers = pinch, wheel = zoom, a tap (no movement) = pick
    var ptrs = {}, tap = null, pinch0 = 0, d0 = 0;
    function wpp() { return (2 * Math.tan(FOV * Math.PI / 360) * cam.d) / H; }
    canvas.addEventListener("pointerdown", function (e) {
      canvas.setPointerCapture(e.pointerId); ptrs[e.pointerId] = { x: e.clientX, y: e.clientY };
      var ids = Object.keys(ptrs);
      tap = ids.length === 1 ? { x: e.clientX, y: e.clientY, moved: false } : null;
      if (ids.length === 2) { var a = ptrs[ids[0]], b = ptrs[ids[1]]; pinch0 = Math.hypot(a.x - b.x, a.y - b.y); d0 = goal.d; }
    });
    canvas.addEventListener("pointermove", function (e) {
      var p = ptrs[e.pointerId];
      if (!p) { hover(e); return; }
      var ids = Object.keys(ptrs);
      if (ids.length === 1) {
        var dx = e.clientX - p.x, dy = e.clientY - p.y;
        if (tap && Math.hypot(e.clientX - tap.x, e.clientY - tap.y) > 6) tap.moved = true;
        if (!tap || tap.moved) { goal.tx -= dx * wpp(); goal.tz -= dy * wpp() / Math.sin(TILT); userMoved = true; clampGoal(); snapIfStatic(); }
        p.x = e.clientX; p.y = e.clientY;
      } else if (ids.length === 2) {
        p.x = e.clientX; p.y = e.clientY;
        var a = ptrs[ids[0]], b = ptrs[ids[1]], dist = Math.hypot(a.x - b.x, a.y - b.y);
        if (pinch0 > 0) { goal.d = d0 * (pinch0 / dist); userMoved = true; clampGoal(); snapIfStatic(); }
      }
    });
    function endPtr(e) {
      var wasTap = tap && !tap.moved && ptrs[e.pointerId];
      delete ptrs[e.pointerId];
      if (Object.keys(ptrs).length < 2) pinch0 = 0;
      if (wasTap && e.type === "pointerup") { var k = pick(e); if (k && hooks.onPick) hooks.onPick(k); }
      tap = null;
    }
    canvas.addEventListener("pointerup", endPtr); canvas.addEventListener("pointercancel", endPtr);
    canvas.addEventListener("wheel", function (e) { e.preventDefault(); goal.d *= Math.exp(e.deltaY * 0.0012); userMoved = true; clampGoal(); snapIfStatic(); }, { passive: false });
    canvas.addEventListener("keydown", function (e) {
      var step = cam.d * 0.06, used = true;
      if (e.key === "ArrowLeft") goal.tx -= step; else if (e.key === "ArrowRight") goal.tx += step; else if (e.key === "ArrowUp") goal.tz -= step; else if (e.key === "ArrowDown") goal.tz += step;
      else if (e.key === "+" || e.key === "=") goal.d *= 0.85; else if (e.key === "-" || e.key === "_") goal.d *= 1.18; else if (e.key === "0") { api.reset(); } else used = false;
      if (used) { e.preventDefault(); userMoved = true; clampGoal(); snapIfStatic(); }
    });
    var ray = new M.Raycaster(), ndc = new M.Vector2();
    function pick(e) {
      var r = canvas.getBoundingClientRect(); ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(ndc, camera);
      var hits = ray.intersectObjects(Object.keys(islands).map(function (k) { return islands[k]; }), true);
      for (var i = 0; i < hits.length; i++) { var o = hits[i].object; while (o && !(o.userData && o.userData.key)) o = o.parent; if (o) return o.userData.key; }
      return null;
    }
    var lastHover = 0;
    function hover(e) {
      var now = performance.now(); if (now - lastHover < 80 || e.pointerType === "touch") return; lastHover = now;
      canvas.style.cursor = pick(e) ? "pointer" : "grab";
    }
    function snapIfStatic() { if (!animOn) { cam = Object.assign({}, goal); } dirty = true; }

    // ------------------------------------------------------------------ frame loop
    var born = performance.now(), clock = new M.Clock(), time = 0, frames = 0, acc = 0, raf = 0, slowChecks = 0, v = new M.Vector3();
    function labels() {
      if (!hooks.onLabels) return;
      var out = [];
      for (var k in islands) {
        var g = islands[k]; v.set(g.position.x, g.position.y + 2.7, g.position.z); v.project(camera);
        out.push({ key: k, x: (v.x * 0.5 + 0.5) * W, y: (-v.y * 0.5 + 0.5) * H, visible: v.z < 1 && Math.abs(v.x) < 1.25 && Math.abs(v.y) < 1.25, s: clamp(34 / cam.d * 1.1, 0.7, 1.15) });
      }
      hooks.onLabels(out);
    }
    function frame() {
      if (disposed) return;
      raf = requestAnimationFrame(frame);
      var dt = Math.min(clock.getDelta(), 0.1); time += dt;
      var moving = Math.abs(goal.tx - cam.tx) + Math.abs(goal.tz - cam.tz) + Math.abs(goal.d - cam.d) > 0.002;
      if (moving) { var k = animOn ? 1 - Math.pow(0.0009, dt) : 1; cam.tx += (goal.tx - cam.tx) * k; cam.tz += (goal.tz - cam.tz) * k; cam.d += (goal.d - cam.d) * k; dirty = true; }
      var popping = false, wall = (performance.now() - born) / 1000;          // wall-clock, so a slow device still finishes the pop-in on time
      for (var i = 0; i < pop.length; i++) {
        var p = pop[i], t = animOn ? clamp((wall - p.t0) / 0.7, 0, 1) : 1;
        var sc = t <= 0 ? 0.001 : (t < 1 ? 1 - Math.pow(1 - t, 3) + Math.sin(t * Math.PI) * 0.08 : 1); p.g.scale.setScalar(Math.max(0.001, sc)); if (t < 1) popping = true;
      }
      for (var gi = grow.length - 1; gi >= 0; gi--) {
        var gr = grow[gi], gt = animOn ? clamp((wall - gr.t0) / 0.6, 0, 1) : 1;
        gr.o.scale.setScalar(Math.max(0.01, gt < 1 ? 1 - Math.pow(1 - gt, 3) : 1)); popping = true; dirty = true;
        if (gt >= 1) grow.splice(gi, 1);
      }
      if (animOn) {
        for (var key in islands) { var g = islands[key]; g.position.y = Math.sin(time * 0.9 + g.userData.phase) * 0.1; }
        floaters.forEach(function (f) { f.o.position.y = f.y + Math.sin(time * f.s + f.p) * 0.12; f.o.rotation.y = Math.sin(time * 0.7 + f.p) * 0.4; });
        clouds.forEach(function (c) { c.position.x += c.userData.speed * dt; if (c.position.x > 50) c.position.x = -50; });
        rings.forEach(function (r) { var s = 1 + Math.sin(time * 1.1 + r.p) * 0.035; r.m.scale.set(s, s, 1); r.m.material.opacity = 0.3 + Math.sin(time * 1.1 + r.p) * 0.08; });
        waterMat.uniforms.uTime.value = time;
      }
      if (animOn || dirty || popping) {
        applyCamera(); renderer.render(scene, camera); labels(); dirty = false;
      }
      // adaptive quality: if frames are slow, drop shadows, then pixel ratio, then ask for the simple map
      acc += dt; frames++;
      if (frames === 90 && animOn) {
        var avg = acc / frames; acc = 0; frames = 0;
        if (avg > 0.034 && slowChecks < 3) {
          slowChecks++;
          if (!low) { low = true; renderer.shadowMap.enabled = false; sun.castShadow = false; renderer.setPixelRatio(1); renderer.setSize(W, H, false); scene.traverse(function (o) { if (o.material) { var ms = [].concat(o.material); ms.forEach(function (m) { m.needsUpdate = true; }); } }); }
          else if (hooks.onSlow) hooks.onSlow(avg);
        }
      }
    }

    // ------------------------------------------------------------------ public API
    var api = {
      resize: resize,
      zoomBy: function (f) { goal.d *= f; userMoved = true; clampGoal(); snapIfStatic(); },
      reset: function () { focusKey = null; userMoved = false; goal = fit(); snapIfStatic(); },
      focus: function (key, off) {
        var g = islands[key]; if (!g) return;
        if (!focusKey) saved = Object.assign({}, goal);
        focusKey = key; off = off || { x: 0, z: 0 };
        goal = { tx: g.position.x + off.x, tz: g.position.z + off.z, d: 15 }; snapIfStatic(); dirty = true;
      },
      unfocus: function () { if (!focusKey) return; focusKey = null; goal = saved || fit(); snapIfStatic(); },
      setAnimation: function (on) { animOn = !!on; dirty = true; },
      isFocused: function () { return !!focusKey; },
      kit: function () { return { landmarks: kit.landmarks, base: kit.base, failed: kit.failed, pending: kit.pending }; },
      dispose: function () {
        disposed = true; cancelAnimationFrame(raf); if (ro) ro.disconnect(); else window.removeEventListener("resize", resize);
        Object.keys(matCache).forEach(function (k) { matCache[k].dispose(); });
        geoms.forEach(function (g) { g.dispose(); }); waterMat.dispose();
        loaded.forEach(function (m) { Object.keys(m).forEach(function (k) { if (m[k] && m[k].isTexture && k !== "envMap") m[k].dispose(); }); m.dispose(); });
        scene.traverse(function (o) { if (o.geometry && geoms.indexOf(o.geometry) < 0) o.geometry.dispose(); });
        if (envTex) envTex.dispose(); renderer.dispose();
        try { renderer.forceContextLoss(); } catch (e) {}
        canvas.remove();
      }
    };
    resize(); applyCamera();
    frame();
    kitStart();
    return api;
  };
})();
