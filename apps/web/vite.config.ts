import { defineConfig } from "vite";

const apiTarget = process.env.MORPHOSTACK_API_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
        // Large microscopy uploads (CZI/LSM) need long timeouts
        timeout: 30 * 60 * 1000,
        proxyTimeout: 30 * 60 * 1000,
      }
    }
  },
  // Packet 12: VTK.js is large; prebundle for dev and keep WebGL volume path offline-friendly.
  optimizeDeps: {
    include: [
      "@kitware/vtk.js/Rendering/Profiles/Volume",
      "@kitware/vtk.js/Rendering/Misc/GenericRenderWindow",
      "@kitware/vtk.js/Common/DataModel/ImageData",
      "@kitware/vtk.js/Common/Core/DataArray",
      "@kitware/vtk.js/Rendering/Core/Volume",
      "@kitware/vtk.js/Rendering/Core/VolumeMapper",
      "@kitware/vtk.js/Rendering/Core/ColorTransferFunction",
      "@kitware/vtk.js/Common/DataModel/PiecewiseFunction"
    ]
  },
  build: {
    chunkSizeWarningLimit: 3500
  }
});
