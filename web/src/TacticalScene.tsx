import { useRef, type CSSProperties } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Edges, Float } from "@react-three/drei";
import * as THREE from "three";

const blocks = [
  { x: -2.9, z: -1.1, h: 0.7 }, { x: -1.9, z: -1.1, h: 1.5 }, { x: -0.9, z: -1.1, h: 0.95 },
  { x: 0.1, z: -1.1, h: 0.45 }, { x: 1.1, z: -1.1, h: 1.85 }, { x: 2.1, z: -1.1, h: 0.72 },
  { x: -2.9, z: 0, h: 1.35 }, { x: -1.9, z: 0, h: 0.52 }, { x: -0.9, z: 0, h: 1.8 },
  { x: 0.1, z: 0, h: 0.85 }, { x: 1.1, z: 0, h: 0.62 }, { x: 2.1, z: 0, h: 1.18 },
  { x: -2.9, z: 1.1, h: 0.62 }, { x: -1.9, z: 1.1, h: 1.05 }, { x: -0.9, z: 1.1, h: 0.42 },
  { x: 0.1, z: 1.1, h: 1.35 }, { x: 1.1, z: 1.1, h: 0.72 }, { x: 2.1, z: 1.1, h: 1.52 },
];

function TacticalGeometry({ accent }: { accent: string }) {
  const group = useRef<THREE.Group>(null);
  useFrame((state, delta) => {
    if (!group.current) return;
    const easing = Math.min(delta * 1.6, 1);
    group.current.rotation.y = THREE.MathUtils.lerp(group.current.rotation.y, -0.16 + state.pointer.x * 0.15, easing);
    group.current.rotation.x = THREE.MathUtils.lerp(group.current.rotation.x, -0.08 + state.pointer.y * 0.08, easing);
  });

  return <>
    <ambientLight intensity={1.35} color="#d5e1da" />
    <directionalLight position={[-4, 8, 5]} intensity={2.8} color={accent} />
    <pointLight position={[4, 3, -2]} intensity={18} distance={13} color="#55a8a0" />
    <gridHelper args={[15, 30, "#88734f", "#465353"]} position={[0, -0.62, 0]} />
    <Float speed={0.42} rotationIntensity={0.015} floatIntensity={0.06}>
      <group ref={group} position={[0, -0.05, 0]}>
        {blocks.map((block, index) => <mesh key={`${block.x}-${block.z}`} position={[block.x, block.h / 2 - 0.48, block.z]} castShadow>
          <boxGeometry args={[0.76, block.h, 0.76]} />
          <meshStandardMaterial color={index % 6 === 0 ? accent : index % 3 === 0 ? "#456f69" : "#354141"} metalness={0.72} roughness={0.38} />
          <Edges scale={1.006} color={index % 6 === 0 ? accent : "#98ada4"} threshold={18} />
        </mesh>)}
      </group>
    </Float>
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.59, 0]}>
      <ringGeometry args={[4.1, 4.12, 96]} />
      <meshBasicMaterial color={accent} transparent opacity={0.65} />
    </mesh>
  </>;
}

export default function TacticalScene({ accent, school }: { accent: string; school: string }) {
  return <section className="scene-header">
    <Canvas dpr={[1, 1.35]} camera={{ position: [0, 4.4, 10.5], fov: 42 }} gl={{ antialias: false, powerPreference: "low-power" }}>
      <TacticalGeometry accent={accent} />
    </Canvas>
    <div className="scene-copy">
      <p className="eyebrow">R6 Match Intelligence / Operations</p>
      <h1>Performance<br />Command</h1>
      <div className="scene-meta"><span className="live-dot" /> {school || "REPLAY ANALYSIS"} <i /> LOCAL DATA LINK</div>
    </div>
    <div className="scene-coordinate">SECTOR 04 <span>·</span> {new Date().toLocaleDateString("en-US", { month: "short", day: "2-digit", year: "numeric" }).toUpperCase()}</div>
    <div className="scene-edge" style={{ "--school-accent": accent } as CSSProperties} />
  </section>;
}