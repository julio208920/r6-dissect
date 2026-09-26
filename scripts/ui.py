"""Lightweight 3D chrome shared by the R6 Match Stats pages."""

from __future__ import annotations

import re

import streamlit as st


def render_tactical_scene(height: int = 210, accent_color: str = "#d49353") -> None:
    """Render a low-cost Three.js tactical grid with a static fallback."""
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", accent_color):
        accent_color = "#d49353"
    accent_three = f"0x{accent_color[1:]}"
    html_doc = """<!doctype html>
<html lang="en">
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&display=swap');
* { box-sizing: border-box; }
html, body { width: 100%; height: 100%; margin: 0; overflow: hidden; background: transparent; }
#stage {
  position: relative; width: 100%; height: 100%; overflow: hidden;
  border: 1px solid rgba(142, 155, 167, .24); border-radius: 5px;
  background: radial-gradient(ellipse at 72% 38%, rgba(45, 86, 91, .26), transparent 42%),
              linear-gradient(112deg, #101619 0%, #182023 56%, #111719 100%);
}
#stage::before {
  content: ""; position: absolute; inset: 0; pointer-events: none; z-index: 1;
  background: linear-gradient(90deg, rgba(13, 18, 20, .93) 0%, rgba(13, 18, 20, .58) 38%, transparent 72%),
              repeating-linear-gradient(0deg, transparent 0 27px, rgba(192, 207, 207, .035) 28px);
}
canvas { position: absolute; inset: 0; width: 100%; height: 100%; }
.copy { position: absolute; z-index: 2; left: clamp(20px, 4vw, 44px); top: 50%; transform: translateY(-50%); color: #e7ebea; font: 12px/1.4 'IBM Plex Sans', sans-serif; }
.eyebrow { color: #d49353; font-size: 10px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }
h1 { margin: 7px 0 4px; font: 600 26px/1.1 'Barlow Condensed', 'Arial Narrow', sans-serif; letter-spacing: 0; }
p { margin: 0; color: #a8b2b1; font-size: 12px; }
.status { display: flex; align-items: center; gap: 8px; margin-top: 17px; color: #c3ccca; font: 10px ui-monospace, monospace; text-transform: uppercase; }
.dot { width: 6px; height: 6px; border-radius: 50%; background: #d49353; box-shadow: 0 0 10px rgba(212,147,83,.5); }
@media (max-width: 560px) { #stage { height: 172px; } .copy { left: 18px; } h1 { font-size: 21px; } p { max-width: 195px; } }
@media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto !important; } }
</style>
</head>
<body>
<div id="stage" aria-label="Animated 3D tactical grid">
  <canvas id="scene"></canvas>
  <div class="copy">
    <div class="eyebrow">R6 Match Intelligence</div>
    <h1>Performance Command</h1>
    <p>Replay analysis, team trends, and season tracking.</p>
    <div class="status"><span class="dot"></span><span>Local analysis ready</span></div>
  </div>
</div>
<script type="module">
import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js";

const stage = document.getElementById("stage");
const canvas = document.getElementById("scene");
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(37, 1, 0.1, 100);
camera.position.set(0, 5.8, 11.5);
const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: false, powerPreference: "low-power" });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.25));
renderer.setClearColor(0x000000, 0);
renderer.outputColorSpace = THREE.SRGBColorSpace;

scene.add(new THREE.HemisphereLight(0xc8d8d2, 0x121719, 2.1));
const key = new THREE.DirectionalLight(0xe7a35b, 2.5);
key.position.set(-3, 8, 5);
scene.add(key);
const fill = new THREE.PointLight(0x5e9b91, 18, 16);
fill.position.set(4, 3, -2);
scene.add(fill);

const grid = new THREE.GridHelper(16, 24, 0x75817e, 0x485451);
grid.position.y = -0.3;
grid.material.transparent = true;
grid.material.opacity = 0.38;
scene.add(grid);

const board = new THREE.Group();
scene.add(board);
const plateGeometry = new THREE.BoxGeometry(0.82, 0.22, 0.82);
const materials = [
  new THREE.MeshStandardMaterial({ color: 0x354240, metalness: 0.72, roughness: 0.38 }),
  new THREE.MeshStandardMaterial({ color: 0xa96839, metalness: 0.55, roughness: 0.32 }),
  new THREE.MeshStandardMaterial({ color: 0x426b67, metalness: 0.62, roughness: 0.36 })
];
const heights = [0.5, 1.15, 0.72, 0.34, 1.65, 0.52, 0.95, 0.4, 1.28, 0.58, 0.36, 0.8, 0.42, 1.02, 0.56, 0.3, 1.4, 0.46, 0.7, 0.34, 0.95, 0.52, 0.28, 0.68];
heights.forEach((height, index) => {
  const x = (index % 6) * 1.13 - 2.82;
  const z = Math.floor(index / 6) * 1.13 - 1.7;
  const material = materials[index % materials.length];
  const plate = new THREE.Mesh(plateGeometry, material);
  plate.scale.y = height;
  plate.position.set(x, height * 0.11, z);
  board.add(plate);
  const outline = new THREE.LineSegments(
    new THREE.EdgesGeometry(plateGeometry),
    new THREE.LineBasicMaterial({ color: index % 5 === 0 ? 0xd49353 : 0x93aaa3, transparent: true, opacity: 0.6 })
  );
  outline.scale.copy(plate.scale);
  outline.position.copy(plate.position);
  board.add(outline);
});

const ring = new THREE.Mesh(
  new THREE.TorusGeometry(4.3, 0.012, 3, 96),
  new THREE.MeshBasicMaterial({ color: 0x81928d, transparent: true, opacity: 0.45 })
);
ring.rotation.x = -Math.PI / 2;
ring.position.y = -0.26;
scene.add(ring);

const pointer = { x: 0, y: 0 };
stage.addEventListener("pointermove", (event) => {
  const bounds = stage.getBoundingClientRect();
  pointer.x = ((event.clientX - bounds.left) / bounds.width - 0.5) * 0.22;
  pointer.y = ((event.clientY - bounds.top) / bounds.height - 0.5) * 0.12;
});
stage.addEventListener("pointerleave", () => { pointer.x = 0; pointer.y = 0; });

const resize = () => {
  const bounds = stage.getBoundingClientRect();
  renderer.setSize(bounds.width, bounds.height, false);
  camera.aspect = bounds.width / bounds.height;
  camera.updateProjectionMatrix();
};
new ResizeObserver(resize).observe(stage);
resize();

const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const render = (time = 0) => {
  const seconds = time * 0.00025;
  board.rotation.y = reducedMotion ? -0.18 : -0.18 + Math.sin(seconds) * 0.04 + pointer.x;
  board.rotation.x = -0.06 + pointer.y;
  camera.position.x += (pointer.x * 3 - camera.position.x) * 0.025;
  camera.lookAt(0, 0, 0);
  renderer.render(scene, camera);
  if (!reducedMotion) requestAnimationFrame(render);
};
render();
</script>
</body>
</html>"""
    html_doc = html_doc.replace("#d49353", accent_color).replace("0xd49353", accent_three)
    if hasattr(st, "iframe"):  # components.html is deprecated in newer Streamlit versions
        st.iframe(html_doc, height=height)
    else:
        import streamlit.components.v1 as components

        components.html(html_doc, height=height, scrolling=False)