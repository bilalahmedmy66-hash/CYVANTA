import { useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Float, Stars, Sparkles } from "@react-three/drei";
import { useReducedMotion } from "framer-motion";

function IntelligenceCore() {
  const group = useRef();
  const ringA = useRef();
  const ringB = useRef();
  const reducedMotion = useReducedMotion();

  useFrame((state, delta) => {
    if (reducedMotion) return;
    if (group.current) group.current.rotation.y += delta * 0.075;
    if (ringA.current) ringA.current.rotation.z += delta * 0.11;
    if (ringB.current) ringB.current.rotation.x -= delta * 0.075;
  });

  return (
    <group ref={group}>
      <Float speed={reducedMotion ? 0 : 0.65} rotationIntensity={reducedMotion ? 0 : 0.08} floatIntensity={reducedMotion ? 0 : 0.12}>
        <mesh>
          <icosahedronGeometry args={[1.04, 2]} />
          <meshStandardMaterial color="#3b82a6" emissive="#22d3ee" emissiveIntensity={0.22} metalness={0.75} roughness={0.2} wireframe />
        </mesh>
        <mesh scale={0.79}>
          <icosahedronGeometry args={[1, 2]} />
          <meshPhysicalMaterial color="#171a3d" emissive="#312e81" emissiveIntensity={0.45} metalness={0.65} roughness={0.18} transparent opacity={0.78} />
        </mesh>
        <mesh ref={ringA} rotation={[0.8, 0.2, 0.2]}>
          <torusGeometry args={[1.39, 0.012, 12, 180]} />
          <meshBasicMaterial color="#22d3ee" />
        </mesh>
        <mesh ref={ringB} rotation={[1.2, 0.2, 0.8]}>
          <torusGeometry args={[1.56, 0.009, 10, 180]} />
          <meshBasicMaterial color="#8b5cf6" />
        </mesh>
        <mesh rotation={[0.3, 0.5, 0]}>
          <torusGeometry args={[1.22, 0.006, 8, 160]} />
          <meshBasicMaterial color="#f472b6" transparent opacity={0.55} />
        </mesh>
      </Float>
      <Sparkles count={55} scale={4.1} size={2} speed={reducedMotion ? 0 : 0.16} color="#8eeeff" />
    </group>
  );
}

export default function CoreView() {
  return (
    <div className="core-stage">
      <div className="core-grid" />
      <div className="core-spotlight" />
      <Canvas camera={{ position: [0, 0, 5.1], fov: 42 }} dpr={[1, 1.5]}>
        <ambientLight intensity={0.95} />
        <pointLight position={[3, 3, 4]} intensity={20} color="#22d3ee" />
        <pointLight position={[-3, -2, 2]} intensity={15} color="#8b5cf6" />
        <pointLight position={[0, 0, 1]} intensity={5} color="#f472b6" />
        <IntelligenceCore />
        <Stars radius={70} depth={35} count={700} factor={2} fade speed={0.18} />
      </Canvas>
      <div className="core-label top-label">CYVANTA INTELLIGENCE CORE</div>
      <div className="core-center"><i /> CORE STANDBY</div>
      <div className="core-label bottom-label">SPATIAL ENVIRONMENT <span>LOCAL VIEW / STANDBY</span></div>
    </div>
  );
}