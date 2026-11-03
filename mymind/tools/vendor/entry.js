// Curated Three.js exports for the 3D model viewer and the island world (tree-shaken by esbuild). Exposed as window.MM3D.
export {
  WebGLRenderer, Scene, PerspectiveCamera, Color, Fog, Group, Object3D, Mesh, Vector2, Vector3, Box3, Raycaster, Plane, Clock, MathUtils,
  AnimationMixer, LoopRepeat, HemisphereLight, DirectionalLight, AmbientLight, PMREMGenerator, ACESFilmicToneMapping, NoToneMapping,
  SRGBColorSpace, PCFSoftShadowMap, DoubleSide, FrontSide, AdditiveBlending,
  PlaneGeometry, CylinderGeometry, ConeGeometry, SphereGeometry, BoxGeometry, TorusGeometry, CapsuleGeometry, RingGeometry, CircleGeometry,
  OctahedronGeometry, IcosahedronGeometry, DodecahedronGeometry, TubeGeometry, CatmullRomCurve3, ExtrudeGeometry, Shape,
  BufferGeometry, BufferAttribute, Float32BufferAttribute,
  MeshStandardMaterial, MeshBasicMaterial, ShadowMaterial, ShaderMaterial, MeshLambertMaterial, TextureLoader, CanvasTexture
} from "three";
export { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
export { DRACOLoader } from "three/examples/jsm/loaders/DRACOLoader.js";
export { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";
export { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
export { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
